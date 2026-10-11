import base64
import json
from datetime import datetime

from .errors import APIError


def encode_cursor(ts: datetime, row_id) -> str:
    raw = json.dumps({"t": ts.isoformat(), "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(data["t"]), data["i"]
    except Exception:
        raise APIError(400, "CURSOR_INVALID", "The pagination cursor is malformed.")


def clamp_limit(limit: int, default: int = 20, maximum: int = 100) -> int:
    return max(1, min(limit or default, maximum))
