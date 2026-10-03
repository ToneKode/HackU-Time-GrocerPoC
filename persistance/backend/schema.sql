-- HacKU Time-Grocer persistence schema
-- Postgres owns the append-only audit ledger and monthly spend.
-- Redis (separate process) owns escalation TTL keys — see redis_client.py.

CREATE TABLE IF NOT EXISTS schema_migrations (
    id          TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hash-chained audit log (cross_team_config.json -> audit).
-- hash = sha256("index|ts|event|status|reason|prev_hash"); thought is NOT hashed.
CREATE TABLE IF NOT EXISTS audit_entries (
    idx         INTEGER PRIMARY KEY CHECK (idx >= 0),
    ts          TEXT NOT NULL,
    event       TEXT NOT NULL,
    status      TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    thought     TEXT NOT NULL DEFAULT '',
    prev_hash   CHAR(64) NOT NULL,
    hash        CHAR(64) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_entries_event_idx ON audit_entries (event);
CREATE INDEX IF NOT EXISTS audit_entries_created_at_idx ON audit_entries (created_at);

-- Monthly spend tracker. Callers may still pass monthly_spent; this is the source of truth when wired.
CREATE TABLE IF NOT EXISTS monthly_spend (
    account_id  TEXT NOT NULL,
    year_month  CHAR(7) NOT NULL,          -- YYYY-MM (UTC)
    spent       NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (spent >= 0),
    currency    CHAR(3) NOT NULL DEFAULT 'HKD',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, year_month)
);

-- Idempotent payment → spend increments (one charge, one add).
CREATE TABLE IF NOT EXISTS spend_ledger (
    id            BIGSERIAL PRIMARY KEY,
    account_id    TEXT NOT NULL,
    year_month    CHAR(7) NOT NULL,
    amount        NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    currency      CHAR(3) NOT NULL DEFAULT 'HKD',
    payment_id    TEXT,
    idempotency_key TEXT,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS spend_ledger_account_ym_idx
    ON spend_ledger (account_id, year_month);

INSERT INTO schema_migrations (id) VALUES ('001_initial')
ON CONFLICT (id) DO NOTHING;
