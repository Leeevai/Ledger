import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import Path

from .authz import ensure, permissions_in_group
from .db import get_conn
from .errors import APIError
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)  # we produce our own 401 body


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    conn=Depends(get_conn),
) -> dict:
    if creds is None:
        raise APIError(
            401,
            "NOT_AUTHENTICATED",
            "Authorization header missing.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise APIError(
            401,
            "TOKEN_EXPIRED",
            "Access token has expired.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    except jwt.InvalidTokenError:
        raise APIError(
            401,
            "TOKEN_INVALID",
            "Access token is not valid.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    row = conn.execute(
        "SELECT id, email, display_name, is_active, created_at FROM users WHERE id = %s",
        (payload["sub"],),
    ).fetchone()

    # The token was signed by us, but the user may have been deleted since.
    if row is None or not row["is_active"]:
        raise APIError(401, "ACCOUNT_UNAVAILABLE", "Account is inactive or missing.")
    return row

def load_expense(
    expense_id: str = Path(..., pattern=r"^exp_[A-Za-z0-9]{6,32}$"),
    user=Depends(current_user),
    conn=Depends(get_conn),
) -> dict:
    row = conn.execute("SELECT * FROM expenses WHERE id = %s", (expense_id,)).fetchone()

    # ── The BOLA defence ──────────────────────────────────────────────
    # Two failures, ONE response. If the expense does not exist we say 404.
    # If it exists but the caller is not in its group we ALSO say 404, so a
    # stranger cannot use response codes to discover which IDs are real.
    if row is None or not permissions_in_group(conn, user["id"], row["group_id"]):
        raise APIError(404, "EXPENSE_NOT_FOUND", "No such expense.")
    return row


def require_expense_permission(permission: str):
    """Dependency factory: gate an endpoint on a permission in the expense's group."""
    def dependency(
        expense=Depends(load_expense),
        user=Depends(current_user),
        conn=Depends(get_conn),
    ) -> dict:
        ensure(conn, user["id"], expense["group_id"], permission)
        return expense
    return dependency


def require_group_permission(permission: str):
    """Same, for endpoints where the group is in the path."""
    def dependency(
        group_id: str = Path(..., pattern=r"^grp_[A-Za-z0-9]{6,32}$"),
        user=Depends(current_user),
        conn=Depends(get_conn),
    ) -> str:
        if not permissions_in_group(conn, user["id"], group_id):
            raise APIError(404, "GROUP_NOT_FOUND", "No such group.")
        ensure(conn, user["id"], group_id, permission)
        return group_id
    return dependency