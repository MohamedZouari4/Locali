"""FastAPI dependency that rejects requests without a valid `Authorization: Bearer <token>` header."""

from fastapi import Header, HTTPException

from app.core.security import is_valid_token


def verify_token(authorization: str = Header(None)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if not is_valid_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")
