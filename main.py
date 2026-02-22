from dotenv import load_dotenv
import os
from stripe import StripeClient
from requests_oauthlib import OAuth2Session
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import json
import time
import datetime
from server import start_server
from random import randint
from webbrowser import open as browser_open
from pprint import pprint
import argparse

# Disable HTTPS requirement for local development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

load_dotenv()

# stripe reporting categories to freeagent category
# https://docs.stripe.com/reports/reporting-categories
# Individual mappings can be overridden via CATEGORY_MAPPING_<key> env vars (e.g. CATEGORY_MAPPING_fee=https://api.freeagent.com/v2/categories/363)
freeagent_category_map = {
    'fee': 'https://api.freeagent.com/v2/categories/363',  # stripe fees
    'charge': 'https://api.freeagent.com/v2/categories/001',  # payments
    'contribution': 'https://api.freeagent.com/v2/categories/360',  # stripe climate
    'refund': 'https://api.freeagent.com/v2/categories/001',
    'dispute': 'https://api.freeagent.com/v2/categories/001',
    'dispute_reversal': 'https://api.freeagent.com/v2/categories/001'
}

# Allow env vars to override or extend the category map
_CATEGORY_MAPPING_PREFIX = 'CATEGORY_MAPPING_'
for env_key, env_value in os.environ.items():
    if env_key.startswith(_CATEGORY_MAPPING_PREFIX):
        category_key = env_key[len(_CATEGORY_MAPPING_PREFIX):].lower()
        freeagent_category_map[category_key] = env_value

stripe_client = StripeClient(os.environ['STRIPE_SECRET_KEY'])

# OAuth2 configuration
CLIENT_ID = os.environ['FREEAGENT_CLIENT_ID']
CLIENT_SECRET = os.environ['FREEAGENT_CLIENT_SECRET']
AUTHORIZATION_BASE_URL = 'https://api.freeagent.com/v2/approve_app'
TOKEN_URL = 'https://api.freeagent.com/v2/token_endpoint'
API_BASE_URL = 'https://api.freeagent.com/v2/'

def create_explanation(bank_transaction_explanation):
    print(session.post('bank_transaction_explanations', json={'bank_transaction_explanation': bank_transaction_explanation}).json())
    print(f"Explained {bank_transaction_explanation['description']}")

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def create_session_with_base_url(token=None):
    """Create an OAuth2Session with the API base URL configured."""
    session = OAuth2Session(CLIENT_ID, token=token)

    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)

    # Mount the adapter for both http and https
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Create a custom request method that prepends the base URL
    original_request = session.request

    def request_with_base_url(method, url, *args, **kwargs):
        if not url.startswith(('http://', 'https://')):
            url = f"{API_BASE_URL.rstrip('/')}/{url.lstrip('/')}"
        return original_request(method, url, *args, **kwargs)

    session.request = request_with_base_url
    return session

def get_session_from_refresh_token():
    """Get a session using a refresh token from environment variables."""
    refresh_token = os.environ.get('FREEAGENT_REFRESH_TOKEN')
    if not refresh_token:
        return None

    try:
        oauth = OAuth2Session(
            CLIENT_ID,
            token={
                'refresh_token': refresh_token,
                'token_type': 'Bearer'
            }
        )
        token = oauth.refresh_token(
            TOKEN_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        return create_session_with_base_url(token)
    except Exception as e:
        print(f"Failed to get session from refresh token: {e}")
        return None

def save_refresh_token_to_env(refresh_token, env_file='.env'):
    """Save the refresh token to the .env file while preserving all existing content."""
    try:
        # Read existing .env file if it exists
        lines = []
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                lines = f.readlines()

        # Find and update or add the refresh token
        refresh_token_line = None
        for i, line in enumerate(lines):
            if line.strip().startswith('FREEAGENT_REFRESH_TOKEN='):
                refresh_token_line = i
                break

        refresh_token_content = f'FREEAGENT_REFRESH_TOKEN={refresh_token}\n'
        if refresh_token_line is not None:
            lines[refresh_token_line] = refresh_token_content
        else:
            # Add a newline before the new token if the file isn't empty
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(refresh_token_content)

        # Write back to .env file
        with open(env_file, 'w') as f:
            f.writelines(lines)

        print(f"Refresh token saved to {env_file}")
    except Exception as e:
        print(f"Failed to save refresh token: {e}")

def freeagent_oauth_flow():
    """Get a session using OAuth flow."""
    port = 80
    while is_port_in_use(port):
        port = randint(8000, 9000)
    redirect_uri = f"http://localhost:{port}"

    oauth = OAuth2Session(
        CLIENT_ID,
        redirect_uri=redirect_uri,
        scope=['full_access']
    )

    authorization_url, state = oauth.authorization_url(AUTHORIZATION_BASE_URL)
    browser_open(authorization_url)
    print(f"If your browser didn't open automatically, go to {authorization_url} to authenticate your FreeAgent account.")

    callback_data = start_server(port)
    # Construct the full redirect URI from the callback data
    redirect_uri_with_params = f"{redirect_uri}?code={callback_data['code']}&state={callback_data['state']}"

    # Verify the state matches what we sent
    if callback_data['state'] != state:
        raise ValueError("State mismatch in OAuth callback")

    token = oauth.fetch_token(
        TOKEN_URL,
        authorization_response=redirect_uri_with_params,
        client_secret=CLIENT_SECRET
    )

    return create_session_with_base_url(token)

def update_refresh_token(session, env_file):
    """Update the refresh token in the specified file if a new one is available."""
    if env_file and 'refresh_token' in session.token:
        print(f"Updating refresh token in {env_file}")
        save_refresh_token_to_env(session.token['refresh_token'], env_file)

def explain_transaction(session, txn):
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
                print(session.post('bank_transaction_explanations', json={'bank_transaction_explanation': payload}).json())
                print(f"Explained {payload['description']}")

                if payout_txn['fee'] > 0:
                    fee_payload = common_payload.copy()
                    fee_payload['category'] = freeagent_category_map['fee']
                    fee_payload['gross_value'] = -payout_txn['fee'] / 100  # fees listed as positive in Stripe response, but need treating as negatives as they're outgoing
                    fee_payload['description'] = f"Stripe processing fees ({payout['id']})"
                    print(session.post('bank_transaction_explanations', json={'bank_transaction_explanation': fee_payload}).json())
                    print(f"Explained {fee_payload['description']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Stripe to FreeAgent reconciliation')
    parser.add_argument('--output-env-file', help='Path to save the refresh token to (if not provided, token will not be saved)')
    args = parser.parse_args()

    # Try to get session from refresh token first
    session = get_session_from_refresh_token()

    # If refresh token fails or doesn't exist, fall back to OAuth flow
    if not session:
        session = freeagent_oauth_flow()

    exception = None
    try:
        for account in session.get('bank_accounts').json()['bank_accounts']:
            txns = session.get(
                'bank_transactions',
                params={'view': 'unexplained', 'bank_account': account['url']}
            ).json()['bank_transactions']
            print(f"{len(txns)} unexplained transactions found in account {account['name']}")
            for t in txns:
                explain_transaction(session, t)
    except Exception as e:
        exception = e

    # Update refresh token if we have a file to save to - even if we failed during processing
    update_refresh_token(session, args.output_env_file)

    # Propagate any errors
    if exception:
        raise exception