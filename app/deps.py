import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_conn
from .errors import APIError
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)   # we produce our own 401 body


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    conn=Depends(get_conn),
) -> dict:
    if creds is None:
        raise APIError(401, "NOT_AUTHENTICATED", "Authorization header missing.",
                       headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise APIError(401, "TOKEN_EXPIRED", "Access token has expired.",
                       headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
    except jwt.InvalidTokenError:
        raise APIError(401, "TOKEN_INVALID", "Access token is not valid.",
                       headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})

    row = conn.execute(
        "SELECT id, email, display_name, is_active, created_at FROM users WHERE id = %s",
        (payload["sub"],),
    ).fetchone()

    # The token was signed by us, but the user may have been deleted since.
    if row is None or not row["is_active"]:
        raise APIError(401, "ACCOUNT_UNAVAILABLE", "Account is inactive or missing.")
    return row
