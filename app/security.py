import time
import bcrypt
import jwt

from .config import settings


# ---------- passwords ----------

def hash_password(plaintext: str) -> str:
    # bcrypt silently truncates at 72 BYTES. Truncate explicitly so behaviour
    # is identical between hashing and verifying, including for multi-byte
    # characters where len(str) != len(bytes).
    raw = plaintext.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode()


def verify_password(plaintext: str, stored_hash: str) -> bool:
    raw = plaintext.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(raw, stored_hash.encode())
    except ValueError:
        return False        # malformed hash in the database




# ---------- tokens ----------

def issue_access_token(user_id: str) -> tuple[str, int]:
    now = int(time.time())
    ttl = settings.access_token_ttl_seconds
    payload = {
        "sub": user_id,          # subject — who this token is about
        "iat": now,              # issued at
        "exp": now + ttl,        # expiry — enforced by the library, not by us
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_access_token(token: str) -> dict:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],   # a LIST, never None
        options={"require": ["exp", "sub"]},
    )
