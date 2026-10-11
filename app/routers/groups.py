import re

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, ConfigDict, Field

from ..authz import permissions_in_group, role_in_group
from ..db import get_conn
from ..deps import current_user, require_group_permission
from ..errors import APIError
from ..ids import new_id

router = APIRouter(prefix="/v1", tags=["groups"])

VALID_ROLES = ("member", "approver", "admin")


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


class MemberPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern=r"^(member|approver|admin)$")


@router.get("/groups")
def my_groups(user=Depends(current_user), conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT g.id, g.slug, g.name, m.role, g.created_at
           FROM memberships m JOIN groups g ON g.id = m.group_id
           WHERE m.user_id = %s ORDER BY g.name""",
        (user["id"],),
    ).fetchall()
    return {"data": rows}


@router.post("/groups", status_code=status.HTTP_201_CREATED)
def create_group(body: GroupCreate, user=Depends(current_user), conn=Depends(get_conn)):
    if conn.execute("SELECT 1 FROM groups WHERE slug = %s", (body.slug,)).fetchone():
        raise APIError(409, "SLUG_TAKEN", "That slug is already in use.")

    gid = new_id("grp")
    group = conn.execute(
        "INSERT INTO groups (id, slug, name) VALUES (%s, %s, %s) RETURNING *",
        (gid, body.slug, body.name),
    ).fetchone()
    # The creator becomes admin — otherwise nobody could ever administer it.
    conn.execute(
        "INSERT INTO memberships (user_id, group_id, role) VALUES (%s, %s, 'admin')",
        (user["id"], gid),
    )
    return group


@router.get("/groups/{group_id}/members")
def list_members(
    group_id: str = Depends(require_group_permission("member:read")),
    conn=Depends(get_conn),
):
    rows = conn.execute(
        """SELECT u.id, u.email, u.display_name, m.role, m.created_at
           FROM memberships m JOIN users u ON u.id = m.user_id
           WHERE m.group_id = %s ORDER BY m.role, u.display_name""",
        (group_id,),
    ).fetchall()
    return {"data": rows}


@router.put("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_200_OK)
def set_member_role(
    body: MemberPut,
    user_id: str = Path(...),
    group_id: str = Depends(require_group_permission("member:manage")),
    actor=Depends(current_user),
    conn=Depends(get_conn),
):
    if not conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone():
        raise APIError(404, "USER_NOT_FOUND", "No such user.")

    # Guard: never let the last admin demote themselves out of existence.
    if user_id == actor["id"] and body.role != "admin":
        others = conn.execute(
            """SELECT count(*) AS n FROM memberships
               WHERE group_id = %s AND role = 'admin' AND user_id <> %s""",
            (group_id, actor["id"]),
        ).fetchone()["n"]
        if others == 0:
            raise APIError(409, "LAST_ADMIN",
                           "Promote another admin before changing your own role.")

    row = conn.execute(
        """INSERT INTO memberships (user_id, group_id, role) VALUES (%s, %s, %s)
           ON CONFLICT (user_id, group_id) DO UPDATE SET role = EXCLUDED.role
           RETURNING user_id, group_id, role, created_at""",
        (user_id, group_id, body.role),
    ).fetchone()
    return row


@router.delete("/groups/{group_id}/members/{user_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: str = Path(...),
    group_id: str = Depends(require_group_permission("member:manage")),
    conn=Depends(get_conn),
):
    conn.execute("DELETE FROM memberships WHERE user_id = %s AND group_id = %s",
                 (user_id, group_id))
    # No 404 if absent: DELETE is idempotent, and the desired state is reached.
    return None


