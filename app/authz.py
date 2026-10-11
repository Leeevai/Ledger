from .errors import APIError

# role -> frozenset(permissions), loaded once at startup.
_PERMISSIONS: dict[str, frozenset[str]] = {}


def load_permission_cache(conn) -> None:
    rows = conn.execute("SELECT role, permission FROM role_permissions").fetchall()
    acc: dict[str, set[str]] = {}
    for r in rows:
        acc.setdefault(r["role"], set()).add(r["permission"])
    global _PERMISSIONS
    _PERMISSIONS = {role: frozenset(p) for role, p in acc.items()}


def role_in_group(conn, user_id: str, group_id: str) -> str | None:
    row = conn.execute(
        "SELECT role FROM memberships WHERE user_id = %s AND group_id = %s",
        (user_id, group_id),
    ).fetchone()
    return row["role"] if row else None


def permissions_in_group(conn, user_id: str, group_id: str) -> frozenset[str]:
    role = role_in_group(conn, user_id, group_id)
    return _PERMISSIONS.get(role, frozenset()) if role else frozenset()


def ensure(conn, user_id: str, group_id: str, permission: str) -> None:
    """Raise 403 unless the user holds `permission` in `group_id`."""
    if permission not in permissions_in_group(conn, user_id, group_id):
        raise APIError(
            403, "PERMISSION_DENIED",
            f"You do not have permission to perform this action.",
            required_permission=permission,     # helps the caller; leaks nothing
        )
