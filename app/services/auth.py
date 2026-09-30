"""Loads the local API token from .auth_token, generating and saving a new random token on first run."""

import os
import secrets

TOKEN_FILE = os.path.abspath(".auth_token")


def get_or_create_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()

    token = secrets.token_hex(32)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    print(f"Generated new API token, saved to {TOKEN_FILE}")
    return token


API_TOKEN = get_or_create_token()
