import os
import secrets

TOKEN_FILE = os.path.abspath(".auth_token")


def get_or_create_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()

    token = secrets.token_hex(32)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    print(f"Generated new API token, saved to {TOKEN_FILE}")
    return token


API_TOKEN = get_or_create_token()
