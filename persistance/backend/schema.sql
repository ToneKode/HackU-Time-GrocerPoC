-- HacKU Time-Grocer persistence schema
-- Postgres owns the append-only audit ledger, monthly spend, and payment records.
-- Redis (separate process) owns escalation TTL keys — see redis_client.py.
-- Payment rows are written by payment/ (:8004), not by the :8003 API.

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

-- Payment control loop (Topic 4). Owned by payment/ :8004.
-- The JWT is kept server-side so authorize can run without the client echoing it.
-- PAN / CVV are never stored.
CREATE TABLE IF NOT EXISTS payments (
    payment_id        TEXT PRIMARY KEY,
    status            TEXT NOT NULL,
    account_id        TEXT NOT NULL,
    amount            NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    currency          CHAR(3) NOT NULL DEFAULT 'HKD',
    merchant          TEXT NOT NULL,
    rail              TEXT NOT NULL,
    purpose           TEXT NOT NULL DEFAULT '',
    intent            TEXT NOT NULL DEFAULT '',
    cart_hash         TEXT NOT NULL DEFAULT '',
    token_jti         TEXT NOT NULL,
    token             TEXT NOT NULL,
    token_expires_at  BIGINT NOT NULL,
    recommendation    JSONB,
    auth_id           TEXT,
    order_id          TEXT,
    receipt_id        TEXT,
    error             TEXT,
    evidence          JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    CONSTRAINT payments_status_chk CHECK (
        status IN ('DRAFT', 'AUTHORIZED', 'CAPTURED', 'FAILED', 'REFUNDED')
    )
);

CREATE INDEX IF NOT EXISTS payments_account_created_idx
    ON payments (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS payments_token_jti_idx ON payments (token_jti);

-- One-time token use. Survives process restart (memory store does not).
CREATE TABLE IF NOT EXISTS payment_jti (
    jti         TEXT PRIMARY KEY,
    payment_id  TEXT,
    used_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (id) VALUES ('001_initial')
ON CONFLICT (id) DO NOTHING;

INSERT INTO schema_migrations (id) VALUES ('002_payments')
ON CONFLICT (id) DO NOTHING;
