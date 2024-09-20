# Stripe -> FreeAgent Reconciliation
Search for unexplained Stripe transactions in a FreeAgent account, recording the original payment value and any associated Stripe fees applied.

## Setup
1. Run `pip install -r requirements.txt` to install all dependencies
2. Create an environment file from the template for all required secrets `cp .env.dist .env`
3. Find your Stripe secret key at https://dashboard.stripe.com/apikeys and add it to the `.env` file (`STRIPE_SECRET_KEY`)
4. Create an app at https://dev.freeagent.com/, and set the "OAuth redirect URIs" to `http://localhost:*`. Add the client ID and client secret to the `.env` file (`FREEAGENT_CLIENT_ID`, `FREEAGENT_CLIENT_SECRET`)
5. Optionally, modify the `freeagent_category_map` dictionary in `main.py` to change the categories that each Stripe reporting category maps to in FreeAgent (anything omitted here will not be automatically explained)

## Usage
Run `python main.py` to start the script. It will direct you to your browser to authenticate with your FreeAgent account, and once done, will begin the process of finding any Stripe transactions to explain.