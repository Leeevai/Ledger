-- ============================================================
--  Ledger — schema
-- ============================================================

-- ---------- identity ----------

CREATE TABLE users (
    id             TEXT        PRIMARY KEY,
    email          TEXT        NOT NULL UNIQUE,
    password_hash  TEXT        NOT NULL,
    display_name   TEXT        NOT NULL,
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Case-insensitive uniqueness without the citext extension.
-- "H@x.com" and "h@x.com" are the same account.
CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email));


-- ---------- groups and membership ----------

CREATE TABLE groups (
    id          TEXT        PRIMARY KEY,
    slug        TEXT        NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    role        TEXT PRIMARY KEY,
    description TEXT NOT NULL
);

CREATE TABLE role_permissions (
    role       TEXT NOT NULL REFERENCES roles(role) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    PRIMARY KEY (role, permission)
);

-- The join table. Composite primary key = a user has at most one role per group.
CREATE TABLE memberships (
    user_id    TEXT        NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    group_id   TEXT        NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    role       TEXT        NOT NULL REFERENCES roles(role),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, group_id)
);

-- The PK indexes (user_id, group_id). We also query the other direction
-- ("who is in this group?"), which the PK index cannot serve efficiently.
CREATE INDEX memberships_group_idx ON memberships (group_id, role);


-- ---------- the business object ----------

CREATE TABLE expenses (
    id            TEXT        PRIMARY KEY,
    group_id      TEXT        NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    created_by    TEXT        NOT NULL REFERENCES users(id),
    description   TEXT        NOT NULL CHECK (length(description) BETWEEN 1 AND 500),
    amount_cents  BIGINT      NOT NULL CHECK (amount_cents > 0),
    currency      CHAR(3)     NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    status        TEXT        NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','submitted','approved','rejected','paid')),
    decided_by    TEXT        REFERENCES users(id),
    decided_at    TIMESTAMPTZ,
    decision_note TEXT,
    CHECK (
        (status IN ('approved', 'rejected', 'paid')
         AND decided_by IS NOT NULL
         AND decided_at IS NOT NULL)
        OR
        (status IN ('draft', 'submitted')
         AND decided_by IS NULL
         AND decided_at IS NULL
         AND decision_note IS NULL)
    ),
    receipt_url   TEXT,
    version       INTEGER     NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- THE index that makes cursor pagination correct AND fast.
-- Column order matches the ORDER BY exactly: (created_at DESC, id DESC).
CREATE INDEX expenses_group_cursor_idx
    ON expenses (group_id, created_at DESC, id DESC);


-- ---------- idempotency ----------

CREATE TABLE idempotency_keys (
    key             TEXT        NOT NULL,
    user_id         TEXT        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_hash    TEXT        NOT NULL,
    response_status INTEGER,
    response_body   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (key, user_id)
);

-- Keys expire. Without this, the table grows forever.
CREATE INDEX idempotency_created_idx ON idempotency_keys (created_at);


-- ---------- audit ----------

CREATE TABLE audit_log (
    id          BIGSERIAL   PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id    TEXT,
    group_id    TEXT,
    action      TEXT        NOT NULL,
    target_type TEXT        NOT NULL,
    target_id   TEXT,
    detail      JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX audit_group_cursor_idx
    ON audit_log (group_id, occurred_at DESC, id DESC);
