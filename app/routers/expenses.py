from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..db import get_conn
from ..deps import (current_user, load_expense, require_expense_permission,
                    require_group_permission)
from ..errors import APIError
from ..ids import new_id
from ..idempotency import begin, finish
from ..pagination import clamp_limit, decode_cursor, encode_cursor

router = APIRouter(prefix="/v1", tags=["expenses"])


class ExpenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=500)
    amount_cents: int = Field(gt=0, le=100_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ExpensePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount_cents: int | None = Field(default=None, gt=0, le=100_000_000)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


PUBLIC = ("id", "group_id", "created_by", "description", "amount_cents", "currency",
          "status", "decided_by", "decided_at", "decision_note", "receipt_url",
          "created_at", "updated_at")


def shape(row: dict) -> dict:
    """The wall (Lesson 1). `version` is INTERNAL — it goes in the ETag, not the body."""
    return {k: row[k] for k in PUBLIC}


def etag_of(row: dict) -> str:
    return f'W/"{row["id"]}.{row["version"]}"'


def audit(conn, actor, group_id, action, target_id, **detail):
    from psycopg.types.json import Jsonb
    conn.execute(
        """INSERT INTO audit_log (actor_id, group_id, action, target_type, target_id, detail)
           VALUES (%s, %s, %s, 'expense', %s, %s)""",
        (actor, group_id, action, target_id, Jsonb(detail)),
    )


# ---------- collection ----------

@router.get("/groups/{group_id}/expenses")
def list_expenses(
    group_id: str = Depends(require_group_permission("expense:read")),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    conn=Depends(get_conn),
):
    limit = clamp_limit(limit)
    sql = ["SELECT * FROM expenses WHERE group_id = %s"]
    args: list = [group_id]

    if status_filter:
        sql.append("AND status = %s")          # path=identity, query=qualification
        args.append(status_filter)
    if cursor:
        ts, last_id = decode_cursor(cursor)
        sql.append("AND (created_at, id) < (%s, %s)")   # ← composite, Lesson 9
        args += [ts, last_id]

    sql.append("ORDER BY created_at DESC, id DESC LIMIT %s")
    args.append(limit + 1)                      # fetch one extra to detect "more"

    rows = conn.execute(" ".join(sql), args).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return {
        "data": [shape(r) for r in rows],
        "next_cursor": encode_cursor(rows[-1]["created_at"], rows[-1]["id"])
                       if has_more and rows else None,
        # No total_count: it costs a full COUNT(*) and leaks volume (Lesson 5).
    }


@router.post("/groups/{group_id}/expenses", status_code=status.HTTP_201_CREATED)
def create_expense(
    body: ExpenseCreate,
    response: Response,
    group_id: str = Depends(require_group_permission("expense:create")),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user=Depends(current_user),
    conn=Depends(get_conn),
):
    payload = body.model_dump()
    replay = begin(conn, idempotency_key, user["id"], payload)
    if replay is not None:
        response.status_code = replay["status"]
        response.headers["Idempotent-Replay"] = "true"
        return replay["body"]

    row = conn.execute(
        """INSERT INTO expenses (id, group_id, created_by, description, amount_cents, currency)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (new_id("exp"), group_id, user["id"], body.description,
         body.amount_cents, body.currency),
    ).fetchone()

    audit(conn, user["id"], group_id, "expense.created", row["id"],
          amount_cents=body.amount_cents, currency=body.currency)

    out = shape(row)
    finish(conn, idempotency_key, user["id"], 201, out)
    response.headers["Location"] = f"/v1/expenses/{row['id']}"   # 201 ⇒ Location
    response.headers["ETag"] = etag_of(row)
    return out


# ---------- item ----------

@router.get("/expenses/{expense_id}")
def get_expense(response: Response, expense=Depends(load_expense),
                if_none_match: str | None = Header(None, alias="If-None-Match")):
    tag = etag_of(expense)
    if if_none_match == tag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return shape(expense)


@router.patch("/expenses/{expense_id}")
def patch_expense(
    body: ExpensePatch,
    response: Response,
    expense=Depends(load_expense),
    if_match: str | None = Header(None, alias="If-Match"),
    user=Depends(current_user),
    conn=Depends(get_conn),
):
    from ..authz import permissions_in_group
    perms = permissions_in_group(conn, user["id"], expense["group_id"])
    mine = expense["created_by"] == user["id"]
    if not ("expense:update_any" in perms or (mine and "expense:update_own" in perms)):
        raise APIError(403, "PERMISSION_DENIED", "You cannot modify this expense.")

    if expense["status"] != "draft":
        raise APIError(409, "NOT_EDITABLE",
                       "Only draft expenses can be edited.",
                       current_status=expense["status"])

    if if_match is not None and if_match != etag_of(expense):
        raise APIError(412, "PRECONDITION_FAILED",
                       "The expense changed since you last read it.")

    fields = body.model_dump(exclude_unset=True)     # ← the crucial flag, §26
    if not fields:
        raise APIError(422, "EMPTY_PATCH", "No updatable fields were supplied.")

    sets = ", ".join(f"{k} = %s" for k in fields)
    row = conn.execute(
        f"""UPDATE expenses SET {sets}, version = version + 1, updated_at = now()
            WHERE id = %s RETURNING *""",
        [*fields.values(), expense["id"]],
    ).fetchone()

    audit(conn, user["id"], row["group_id"], "expense.updated", row["id"],
          changed=list(fields))
    response.headers["ETag"] = etag_of(row)
    return shape(row)


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense=Depends(require_expense_permission("expense:delete")),
                   user=Depends(current_user), conn=Depends(get_conn)):
    conn.execute("DELETE FROM expenses WHERE id = %s", (expense["id"],))
    audit(conn, user["id"], expense["group_id"], "expense.deleted", expense["id"])
    return None


# ---------- singleton sub-resource ----------

class ReceiptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(pattern=r"^https://", max_length=1000)


@router.put("/expenses/{expense_id}/receipt")
def put_receipt(body: ReceiptIn, expense=Depends(load_expense),
                user=Depends(current_user), conn=Depends(get_conn)):
    # PUT, not POST: an expense has exactly ONE receipt. Assignment ⇒ idempotent.
    row = conn.execute(
        """UPDATE expenses SET receipt_url = %s, version = version + 1, updated_at = now()
           WHERE id = %s RETURNING *""",
        (body.url, expense["id"]),
    ).fetchone()
    return {"url": row["receipt_url"]}


# ---------- state transitions ----------

def transition(conn, expense, user, *, frm: tuple[str, ...], to: str,
               action: str, note: str | None):
    if expense["status"] not in frm:
        raise APIError(409, "INVALID_TRANSITION",
                       f"Cannot move an expense from '{expense['status']}' to '{to}'.",
                       current_status=expense["status"], allowed_from=list(frm))
    row = conn.execute(
        """UPDATE expenses
           SET status = %s, decided_by = %s, decided_at = now(),
               decision_note = %s, version = version + 1, updated_at = now()
           WHERE id = %s AND status = %s
           RETURNING *""",
        (to, user["id"], note, expense["id"], expense["status"]),
    ).fetchone()
    # AND status = %s makes the transition safe under concurrency: if another
    # request won the race, zero rows update and we report the conflict.
    if row is None:
        raise APIError(409, "CONCURRENT_TRANSITION",
                       "Another request changed this expense first.")
    audit(conn, user["id"], row["group_id"], action, row["id"], note=note)
    return row


@router.post("/expenses/{expense_id}/submission", status_code=status.HTTP_201_CREATED)
def submit(body: DecisionIn, expense=Depends(load_expense),
           user=Depends(current_user), conn=Depends(get_conn)):
    if expense["created_by"] != user["id"]:
        raise APIError(403, "PERMISSION_DENIED", "Only the author may submit an expense.")
    row = transition(conn, expense, user, frm=("draft",), to="submitted",
                     action="expense.submitted", note=body.note)
    return shape(row)


@router.post("/expenses/{expense_id}/approval", status_code=status.HTTP_201_CREATED)
def approve(body: DecisionIn,
            expense=Depends(require_expense_permission("expense:approve")),
            user=Depends(current_user), conn=Depends(get_conn)):
    # Separation of duties: you may not approve your own spending.
    if expense["created_by"] == user["id"]:
        raise APIError(403, "SELF_APPROVAL_FORBIDDEN",
                       "You cannot approve an expense you created.")
    row = transition(conn, expense, user, frm=("submitted",), to="approved",
                     action="expense.approved", note=body.note)
    return shape(row)


@router.post("/expenses/{expense_id}/rejection", status_code=status.HTTP_201_CREATED)
def reject(body: DecisionIn,
           expense=Depends(require_expense_permission("expense:reject")),
           user=Depends(current_user), conn=Depends(get_conn)):
    row = transition(conn, expense, user, frm=("submitted",), to="rejected",
                     action="expense.rejected", note=body.note)
    return shape(row)


# ---------- audit log ----------

@router.get("/groups/{group_id}/audit-log")
def audit_log(
    group_id: str = Depends(require_group_permission("member:read")),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    conn=Depends(get_conn),
):
    sql = ["SELECT id, occurred_at, actor_id, action, target_type, target_id, detail",
           "FROM audit_log WHERE group_id = %s"]
    args: list = [group_id]
    if cursor:
        ts, last_id = decode_cursor(cursor)
        sql.append("AND (occurred_at, id) < (%s, %s)")
        args += [ts, int(last_id)]
    sql.append("ORDER BY occurred_at DESC, id DESC LIMIT %s")
    args.append(limit + 1)

    rows = conn.execute(" ".join(sql), args).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "data": rows,
        "next_cursor": encode_cursor(rows[-1]["occurred_at"], rows[-1]["id"])
                       if has_more and rows else None,
    }
