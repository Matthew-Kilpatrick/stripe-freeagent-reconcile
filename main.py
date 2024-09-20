from dotenv import load_dotenv
import os
from stripe import StripeClient
from rauth import OAuth2Service
import json
import time
import datetime
from server import start_server
from random import randint
from webbrowser import open as browser_open

load_dotenv()

# stripe reporting categories to freeagent category
# https://docs.stripe.com/reports/reporting-categories
freeagent_category_map = {
    'fee': 'https://api.freeagent.com/v2/categories/363',  # stripe fees
    'charge': 'https://api.freeagent.com/v2/categories/001',  # payments
    'contribution': 'https://api.freeagent.com/v2/categories/360',  # stripe climate
    'refund': 'https://api.freeagent.com/v2/categories/001',
    'dispute': 'https://api.freeagent.com/v2/categories/001',
    'dispute_reversal': 'https://api.freeagent.com/v2/categories/001'
}

stripe_client = StripeClient(os.environ['STRIPE_SECRET_KEY'])

freeagent_oauth = OAuth2Service(
    client_id=os.environ['FREEAGENT_CLIENT_ID'],
    client_secret=os.environ['FREEAGENT_CLIENT_SECRET'],
    name='freeagent',
    authorize_url='https://api.freeagent.com/v2/approve_app',
    access_token_url='https://api.freeagent.com/v2/token_endpoint',
    base_url='https://api.freeagent.com/v2/'
)

def create_explanation(bank_transaction_explanation):
    print(session.post('bank_transaction_explanations', json={'bank_transaction_explanation': bank_transaction_explanation}).json())
    print(f"Explained {bank_transaction_explanation['description']}")

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def freeagent_oauth_flow():
    port = 80
    while is_port_in_use(port):
        port = randint(8000, 9000)
    redirect_uri = f"http://localhost:{port}"
    oauth_uri = freeagent_oauth.get_authorize_url(redirect_uri=redirect_uri, response_type='code')
    browser_open(oauth_uri)
    print(f"If your browser didn't open automatically, go to {oauth_uri} to authenticate your FreeAgent account.")
    callback_data = start_server(port)

    return freeagent_oauth.get_auth_session(data={'grant_type': 'authorization_code', 'code': callback_data['code'], 'redirect_uri': redirect_uri}, decoder=json.loads)

def explain_transaction(txn):
    if not txn['description'].startswith('Stripe Payments'):
        return
    date = txn['dated_on']
    # convert YYYY-MM-DD date to unix timestamp
    date_start = int(time.mktime(datetime.datetime.strptime(date, "%Y-%m-%d").timetuple()))
    date_end = date_start + 86400

    payouts = stripe_client.payouts.list({'arrival_date': {'gte': date_start, 'lt': date_end}})
    for payout in payouts['data']:
        if payout['amount'] == round(float(txn['amount']) * 100):
            print(f"Matched payout {payout['id']} to transaction {txn['url']}")
            stripe_client.payouts.update(payout['id'], {'metadata': {'freeagent_transaction': txn['url']}})

            common_payload = {
                'bank_transaction': txn['url'],
                'dated_on': txn['dated_on']
            }

            payout_txns = stripe_client.balance_transactions.list({'payout': payout['id']})
            for payout_txn in payout_txns['data']:
                if payout_txn['type'] == 'payout':
                    # this is the amount sent to bank, we don't need to explain this, everything else will sum to it
                    continue
                if payout_txn['reporting_category'] not in freeagent_category_map:
                    print(f"Unknown reporting category {payout_txn['reporting_category']}")
                    continue

                payload = common_payload.copy()
                payload['category'] = freeagent_category_map[payout_txn['reporting_category']]
                payload['gross_value'] = payout_txn['amount'] / 100  # negative = outgoing
                payload['description'] = f"{payout_txn['description']} ({payout['id']})"
                create_explanation(payload)

                if payout_txn['fee'] > 0:
                    fee_payload = common_payload.copy()
                    fee_payload['category'] = freeagent_category_map['fee']
                    fee_payload['gross_value'] = -payout_txn['fee'] / 100  # fees listed as positive in Stripe response, but need treating as negatives as they're outgoing
                    fee_payload['description'] = f"Stripe processing fees ({payout['id']})"
                    create_explanation(fee_payload)

if __name__ == "__main__":
    session = freeagent_oauth_flow()
    for account in session.get('bank_accounts').json()['bank_accounts']:
        txns = session.get(
            'bank_transactions',
            params={'view': 'unexplained', 'bank_account': account['url']}
        ).json()['bank_transactions']
        print(f"{len(txns)} unexplained transactions found in account {account['name']}")
        for t in txns:
            explain_transaction(t)