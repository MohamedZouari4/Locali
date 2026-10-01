"""Loads the local API token from .auth_token in the repository root, generating and saving
a new random token on first run.
"""

import os
import secrets

from app.core.config import TOKEN_FILE


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


def is_valid_token(token):
    # Constant-time comparison, so response timing does not leak how much of the token matched.
    return secrets.compare_digest(token or "", API_TOKEN)
