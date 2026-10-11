import hashlib
import json

from psycopg.types.json import Jsonb

from .errors import APIError


def _hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin(conn, key: str | None, user_id: str, payload: dict) -> dict | None:
    """Claim an idempotency key.

    Returns the STORED response if this key was already completed, or None if
    this is a fresh request that should proceed.
    """
    if key is None:
        return None
    if not (8 <= len(key) <= 255):
        raise APIError(400, "IDEMPOTENCY_KEY_INVALID",
                       "Idempotency-Key must be 8-255 characters.")

    request_hash = _hash(payload)

    # Atomic claim: either we insert the row, or someone already has it.
    claimed = conn.execute(
        """INSERT INTO idempotency_keys (key, user_id, request_hash)
           VALUES (%s, %s, %s)
           ON CONFLICT (key, user_id) DO NOTHING
           RETURNING key""",
        (key, user_id, request_hash),
    ).fetchone()
    if claimed:
        return None                      # we own it — proceed

    prior = conn.execute(
        """SELECT request_hash, response_status, response_body
           FROM idempotency_keys WHERE key = %s AND user_id = %s""",
        (key, user_id),
    ).fetchone()

    # Same key, DIFFERENT body: the client has a bug. Refuse loudly.
    if prior["request_hash"] != request_hash:
        raise APIError(422, "IDEMPOTENCY_KEY_REUSED",
                       "This Idempotency-Key was already used with a different request body.")

    # Same key, same body, but the first attempt hasn't finished yet.
    if prior["response_status"] is None:
        raise APIError(409, "REQUEST_IN_PROGRESS",
                       "A request with this Idempotency-Key is still in flight.",
                       headers={"Retry-After": "1"})

    return {"status": prior["response_status"], "body": prior["response_body"]}


def finish(conn, key: str | None, user_id: str, status: int, body: dict) -> None:
    if key is None:
        return
    conn.execute(
        """UPDATE idempotency_keys SET response_status = %s, response_body = %s
           WHERE key = %s AND user_id = %s""",
        (status, Jsonb(body), key, user_id),
    )
