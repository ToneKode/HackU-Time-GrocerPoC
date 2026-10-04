-- HacKU Time-Grocer — Postgres schema (Person 2 / infra)
-- Aligned with agent-brain/cross_team_config.json + frontend/contract.json
-- Currency: HKD. Money columns use NUMERIC(12,2).

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

CREATE TYPE merchant_list_status AS ENUM ('whitelist', 'blacklist', 'neutral');

CREATE TYPE mandate_status AS ENUM (
  'received',
  'needs_clarification',
  'planning',
  'ready',
  'completed',
  'halted',
  'escalated',
  'aborted',
  'failed',
  'revoked',
  'duplicate_blocked'
);

CREATE TYPE policy_decision AS ENUM ('PASS', 'ESCALATE', 'HALT');

CREATE TYPE escalation_status AS ENUM ('PENDING', 'APPROVED', 'REFUSED', 'EXPIRED');

CREATE TYPE escalation_decision AS ENUM ('APPROVE', 'REFUSE');

CREATE TYPE order_status AS ENUM (
  'draft',
  'awaiting_payment',
  'completed',
  'payment_failed',
  'refunded',
  'cancelled'
);

CREATE TYPE payment_route AS ENUM ('mastercard', 'unionpay');

CREATE TYPE violation_rule AS ENUM (
  'merchant_blacklisted',
  'merchant_not_whitelisted',
  'banned_category',
  'per_transaction_cap',
  'monthly_cap',
  'bulk_ceiling',
  'duplicate',
  'mandate_revoked',
  'escalation_expired',
  'late_approval_ignored',
  'payment_failure',
  'final_verification_failure',
  'prompt_injection',
  'ambiguous_mandate'
);

-- ---------------------------------------------------------------------------
-- Users & policy settings (FR1)
-- ---------------------------------------------------------------------------

CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           TEXT NOT NULL UNIQUE,
  display_name    TEXT NOT NULL,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE users IS 'Logged-in guardians (e.g. mother). Guests have no row.';

CREATE TABLE user_policies (
  user_id               UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  per_transaction_cap   NUMERIC(12,2) NOT NULL DEFAULT 500.00
                        CHECK (per_transaction_cap >= 0),
  bulk_ceiling          NUMERIC(12,2) NOT NULL DEFAULT 800.00
                        CHECK (bulk_ceiling >= 0),
  monthly_cap           NUMERIC(12,2) NOT NULL DEFAULT 2000.00
                        CHECK (monthly_cap >= 0),
  monthly_spent         NUMERIC(12,2) NOT NULL DEFAULT 0.00
                        CHECK (monthly_spent >= 0),
  monthly_period_start  DATE NOT NULL DEFAULT date_trunc('month', now())::date,
  escalation_ttl_seconds INTEGER NOT NULL DEFAULT 600
                        CHECK (escalation_ttl_seconds > 0),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bulk_gte_per_tx CHECK (bulk_ceiling >= per_transaction_cap)
);

COMMENT ON TABLE user_policies IS
  'R2/R3/R4 knobs. monthly_spent is authoritative for HALT checks.';

-- Tokenized payment credentials only (NFR1). Never store PAN/CVV.
CREATE TABLE payment_methods (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  route         payment_route NOT NULL,
  token_ref     TEXT NOT NULL,
  label         TEXT NOT NULL,
  is_default    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, route, token_ref)
);

CREATE UNIQUE INDEX payment_methods_one_default_per_user
  ON payment_methods (user_id)
  WHERE is_default;

-- ---------------------------------------------------------------------------
-- Catalog (guest-readable official merchant prices)
-- ---------------------------------------------------------------------------

CREATE TABLE merchants (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL UNIQUE,
  list_status   merchant_list_status NOT NULL DEFAULT 'neutral',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE category_rules (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
  category      TEXT NOT NULL,
  is_banned     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- NULL user_id = global rule; Postgres UNIQUE treats NULLs as distinct
CREATE UNIQUE INDEX category_rules_user_category_uidx
  ON category_rules (user_id, category)
  WHERE user_id IS NOT NULL;

CREATE UNIQUE INDEX category_rules_global_category_uidx
  ON category_rules (category)
  WHERE user_id IS NULL;

COMMENT ON TABLE category_rules IS
  'NULL user_id = global blacklist. Per-user rows override for that user.';

CREATE TABLE products (
  sku           TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  price         NUMERIC(12,2) NOT NULL CHECK (price >= 0),
  currency      CHAR(3) NOT NULL DEFAULT 'HKD',
  merchant_id   UUID NOT NULL REFERENCES merchants(id),
  category      TEXT NOT NULL,
  stock         INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  image_url     TEXT NOT NULL DEFAULT '',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  name_is_untrusted BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN products.name_is_untrusted IS
  'Product copy must never be executed as agent instructions (prompt injection demos).';

CREATE INDEX products_merchant_idx ON products (merchant_id);
CREATE INDEX products_category_idx ON products (category);
CREATE INDEX products_name_trgm_support ON products (lower(name));

-- ---------------------------------------------------------------------------
-- Mandates (natural language orders)
-- ---------------------------------------------------------------------------

CREATE TABLE mandates (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id),
  raw_intent        TEXT NOT NULL,
  parsed_query      TEXT,
  qty               INTEGER CHECK (qty IS NULL OR qty > 0),
  budget_hint_hkd   NUMERIC(12,2) CHECK (budget_hint_hkd IS NULL OR budget_hint_hkd >= 0),
  status            mandate_status NOT NULL DEFAULT 'received',
  clarifying_question TEXT,
  idempotency_key   TEXT,
  revoked_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX mandates_user_created_idx ON mandates (user_id, created_at DESC);
CREATE INDEX mandates_status_idx ON mandates (status);

CREATE TABLE mandate_line_items (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mandate_id    UUID NOT NULL REFERENCES mandates(id) ON DELETE CASCADE,
  sku           TEXT REFERENCES products(sku),
  requested_name TEXT,
  category      TEXT,
  qty           INTEGER NOT NULL DEFAULT 1 CHECK (qty > 0),
  unit_price    NUMERIC(12,2),
  line_total    NUMERIC(12,2),
  merchant_name TEXT,
  is_compliant  BOOLEAN,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX mandate_lines_mandate_idx ON mandate_line_items (mandate_id);

-- ---------------------------------------------------------------------------
-- Policy evaluations & violations
-- ---------------------------------------------------------------------------

CREATE TABLE policy_checks (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mandate_id          UUID REFERENCES mandates(id) ON DELETE SET NULL,
  user_id             UUID NOT NULL REFERENCES users(id),
  merchant            TEXT,
  category            TEXT,
  sku                 TEXT,
  qty                 INTEGER,
  amount              NUMERIC(12,2) NOT NULL,
  currency            CHAR(3) NOT NULL DEFAULT 'HKD',
  monthly_spent       NUMERIC(12,2) NOT NULL,
  monthly_remaining   NUMERIC(12,2) NOT NULL,
  per_transaction_cap NUMERIC(12,2) NOT NULL,
  monthly_cap         NUMERIC(12,2) NOT NULL,
  bulk_ceiling        NUMERIC(12,2) NOT NULL,
  status              policy_decision NOT NULL,
  reason              TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policy_violations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mandate_id    UUID REFERENCES mandates(id) ON DELETE CASCADE,
  policy_check_id UUID REFERENCES policy_checks(id) ON DELETE CASCADE,
  sku           TEXT,
  category      TEXT,
  merchant      TEXT,
  rule          violation_rule NOT NULL,
  detail        TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Escalations (R3 + 10-minute human-in-the-loop)
-- Redis owns the TTL key; Postgres owns durable status / late-approval flag.
-- ---------------------------------------------------------------------------

CREATE TABLE escalations (
  escalation_id         TEXT PRIMARY KEY,
  user_id               UUID NOT NULL REFERENCES users(id),
  mandate_id            UUID REFERENCES mandates(id) ON DELETE SET NULL,
  status                escalation_status NOT NULL DEFAULT 'PENDING',
  ttl_seconds           INTEGER NOT NULL DEFAULT 600,
  amount                NUMERIC(12,2) NOT NULL,
  currency              CHAR(3) NOT NULL DEFAULT 'HKD',
  merchant              TEXT NOT NULL,
  sku                   TEXT NOT NULL,
  qty                   INTEGER NOT NULL DEFAULT 1,
  reason                TEXT NOT NULL,
  signature             TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at            TIMESTAMPTZ NOT NULL,
  decided_at            TIMESTAMPTZ,
  decision              escalation_decision,
  approval_attempt_at   TIMESTAMPTZ,
  late_approval_ignored BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX escalations_user_status_idx ON escalations (user_id, status);
CREATE INDEX escalations_expires_idx ON escalations (expires_at)
  WHERE status = 'PENDING';

-- ---------------------------------------------------------------------------
-- Orders & payments
-- ---------------------------------------------------------------------------

CREATE TABLE orders (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  public_order_id     TEXT NOT NULL UNIQUE,
  user_id             UUID NOT NULL REFERENCES users(id),
  mandate_id          UUID REFERENCES mandates(id) ON DELETE SET NULL,
  escalation_id       TEXT REFERENCES escalations(escalation_id),
  status              order_status NOT NULL DEFAULT 'draft',
  subtotal            NUMERIC(12,2) NOT NULL DEFAULT 0,
  shipping_fee        NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax                 NUMERIC(12,2) NOT NULL DEFAULT 0,
  reward_discount     NUMERIC(12,2) NOT NULL DEFAULT 0,
  total_landed_cost   NUMERIC(12,2) NOT NULL DEFAULT 0,
  currency            CHAR(3) NOT NULL DEFAULT 'HKD',
  free_shipping_threshold NUMERIC(12,2) NOT NULL DEFAULT 400,
  payment_route       payment_route,
  charged             NUMERIC(12,2),
  reward_points_earned INTEGER,
  payment_error       TEXT,
  reasoning_report    JSONB NOT NULL DEFAULT '{}'::jsonb,
  paid_at             TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN orders.reasoning_report IS
  'Why this SKU / payment route was chosen (agent explainability for UI).';

CREATE INDEX orders_user_created_idx ON orders (user_id, created_at DESC);
CREATE INDEX orders_mandate_idx ON orders (mandate_id);

CREATE TABLE order_line_items (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id      UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  sku           TEXT NOT NULL,
  name          TEXT NOT NULL,
  merchant      TEXT NOT NULL,
  category      TEXT NOT NULL,
  unit_price    NUMERIC(12,2) NOT NULL,
  qty           INTEGER NOT NULL CHECK (qty > 0),
  line_total    NUMERIC(12,2) NOT NULL
);

CREATE INDEX order_lines_order_idx ON order_line_items (order_id);

-- Idempotency: user + SKU + mandate + time window (NFR2)
CREATE TABLE idempotency_keys (
  key               TEXT PRIMARY KEY,
  user_id           UUID NOT NULL REFERENCES users(id),
  mandate_id        UUID REFERENCES mandates(id) ON DELETE SET NULL,
  order_id          UUID REFERENCES orders(id) ON DELETE SET NULL,
  sku               TEXT,
  window_start      TIMESTAMPTZ NOT NULL DEFAULT now(),
  window_seconds    INTEGER NOT NULL DEFAULT 86400,
  response_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idempotency_user_sku_window_idx
  ON idempotency_keys (user_id, sku, window_start DESC);

-- ---------------------------------------------------------------------------
-- Hash-chained audit ledger (FR7 / NFR4)
-- ---------------------------------------------------------------------------

CREATE TABLE audit_log (
  id            BIGSERIAL PRIMARY KEY,
  chain_index   INTEGER NOT NULL,
  chain_id      UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  user_id       UUID REFERENCES users(id),
  mandate_id    UUID REFERENCES mandates(id) ON DELETE SET NULL,
  ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
  event         TEXT NOT NULL,
  status        TEXT NOT NULL,
  reason        TEXT NOT NULL DEFAULT '',
  thought       TEXT NOT NULL DEFAULT '',
  prev_hash     CHAR(64) NOT NULL,
  hash          CHAR(64) NOT NULL,
  payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (chain_id, chain_index),
  UNIQUE (chain_id, hash)
);

CREATE INDEX audit_log_chain_idx ON audit_log (chain_id, chain_index);
CREATE INDEX audit_log_mandate_idx ON audit_log (mandate_id);
CREATE INDEX audit_log_user_ts_idx ON audit_log (user_id, ts DESC);

COMMENT ON TABLE audit_log IS
  'Tamper-evident ledger. hash = sha256(index|ts|event|status|reason|prev_hash).';

-- Helper: append a chained event (used by seed / policy API)
CREATE OR REPLACE FUNCTION audit_append(
  p_chain_id UUID,
  p_user_id UUID,
  p_mandate_id UUID,
  p_event TEXT,
  p_status TEXT,
  p_reason TEXT,
  p_thought TEXT DEFAULT '',
  p_payload JSONB DEFAULT '{}'::jsonb,
  p_ts TIMESTAMPTZ DEFAULT now()
) RETURNS audit_log
LANGUAGE plpgsql
AS $$
DECLARE
  v_prev audit_log;
  v_index INTEGER;
  v_prev_hash CHAR(64);
  v_ts_text TEXT;
  v_material TEXT;
  v_hash CHAR(64);
  v_row audit_log;
BEGIN
  SELECT * INTO v_prev
  FROM audit_log
  WHERE chain_id = p_chain_id
  ORDER BY chain_index DESC
  LIMIT 1
  FOR UPDATE;

  IF v_prev IS NULL THEN
    v_index := 0;
    v_prev_hash := repeat('0', 64);
  ELSE
    v_index := v_prev.chain_index + 1;
    v_prev_hash := v_prev.hash;
  END IF;

  v_ts_text := to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
  v_material := v_index::text || '|' || v_ts_text || '|' || p_event || '|' ||
                p_status || '|' || p_reason || '|' || v_prev_hash;
  v_hash := encode(digest(v_material, 'sha256'), 'hex');

  INSERT INTO audit_log (
    chain_index, chain_id, user_id, mandate_id, ts, event, status, reason,
    thought, prev_hash, hash, payload
  ) VALUES (
    v_index, p_chain_id, p_user_id, p_mandate_id, p_ts, p_event, p_status,
    p_reason, COALESCE(p_thought, ''), v_prev_hash, v_hash, p_payload
  )
  RETURNING * INTO v_row;

  RETURN v_row;
END;
$$;

-- Verify chain integrity; returns broken index or NULL if intact
CREATE OR REPLACE FUNCTION audit_verify_chain(p_chain_id UUID)
RETURNS TABLE (broken_index INTEGER, expected_hash TEXT, actual_hash TEXT)
LANGUAGE plpgsql
AS $$
DECLARE
  r audit_log;
  v_ts_text TEXT;
  v_material TEXT;
  v_expected CHAR(64);
  v_prev CHAR(64) := repeat('0', 64);
BEGIN
  FOR r IN
    SELECT * FROM audit_log
    WHERE chain_id = p_chain_id
    ORDER BY chain_index
  LOOP
    IF r.prev_hash <> v_prev THEN
      broken_index := r.chain_index;
      expected_hash := v_prev;
      actual_hash := r.prev_hash;
      RETURN NEXT;
      RETURN;
    END IF;
    v_ts_text := to_char(r.ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
    v_material := r.chain_index::text || '|' || v_ts_text || '|' || r.event || '|' ||
                  r.status || '|' || r.reason || '|' || r.prev_hash;
    v_expected := encode(digest(v_material, 'sha256'), 'hex');
    IF v_expected <> r.hash THEN
      broken_index := r.chain_index;
      expected_hash := v_expected;
      actual_hash := r.hash;
      RETURN NEXT;
      RETURN;
    END IF;
    v_prev := r.hash;
  END LOOP;
END;
$$;

COMMIT;
