from fastapi import APIRouter, Depends, status

from ..db import get_conn
from ..deps import current_user
from ..errors import APIError
from ..ids import new_id
from ..schemas import UserCreate, UserOut, UserPatch
from ..security import hash_password

router = APIRouter(prefix="/v1", tags=["users"])


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, conn=Depends(get_conn)):
    existing = conn.execute(
        "SELECT 1 FROM users WHERE lower(email) = lower(%s)", (body.email,)
    ).fetchone()
    if existing:
        # 409, not 422: the request is well-formed, the WORLD conflicts with it.
        raise APIError(409, "EMAIL_TAKEN", "An account with that email already exists.")

    return conn.execute(
        """INSERT INTO users (id, email, password_hash, display_name)
           VALUES (%s, %s, %s, %s)
           RETURNING id, email, display_name, created_at""",
        (new_id("usr"), body.email, hash_password(body.password), body.display_name),
    ).fetchone()


@router.get("/users/me", response_model=UserOut)
def me(user=Depends(current_user)):
    return user


@router.patch("/users/me", response_model=UserOut)
def update_me(body: UserPatch, user=Depends(current_user), conn=Depends(get_conn)):
    fields = body.model_dump(exclude_unset=True)     # ← see §26
    if not fields:
        raise APIError(422, "EMPTY_PATCH", "No updatable fields were supplied.")
    return conn.execute(
        """UPDATE users SET display_name = %s, updated_at = now()
           WHERE id = %s
           RETURNING id, email, display_name, created_at""",
        (fields["display_name"], user["id"]),
    ).fetchone()
