from fastapi import APIRouter, Depends, Response, status

from ..db import get_conn
from ..deps import current_user
from ..errors import APIError
from ..schemas import LoginIn, TokenOut
from ..security import issue_access_token, verify_password

router = APIRouter(prefix="/v1", tags=["sessions"])


@router.post("/sessions", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def login(body: LoginIn, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT id, password_hash, is_active FROM users WHERE lower(email) = lower(%s)",
        (body.email,),
    ).fetchone()

    # Identical response for "no such user" and "wrong password" — otherwise
    # login becomes an account-enumeration oracle.
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise APIError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    if not row["is_active"]:
        raise APIError(403, "ACCOUNT_DISABLED", "This account has been disabled.")

    token, ttl = issue_access_token(row["id"])
    return TokenOut(access_token=token, expires_in=ttl)


@router.delete("/sessions/current", status_code=status.HTTP_204_NO_CONTENT)
def logout(user=Depends(current_user)):
    # Honest about the limitation: a stateless JWT cannot be revoked.
    # The client must discard it. §37 fixes this properly.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
