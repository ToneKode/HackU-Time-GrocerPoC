-- HacKU Time-Grocer persistence schema (MySQL 8)
-- Audit ledger, monthly spend, shopper profile, orders, and the product shelf.
-- Redis (separate process) owns escalation TTL keys — see redis_client.py.

CREATE TABLE IF NOT EXISTS schema_migrations (
    id          VARCHAR(64) PRIMARY KEY,
    applied_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Hash-chained audit log. hash = sha256("index|ts|event|status|reason|prev_hash").
-- thought is stored for the UI trace and is NOT part of the hash.
CREATE TABLE IF NOT EXISTS audit_entries (
    idx         INTEGER PRIMARY KEY,
    ts          VARCHAR(32) NOT NULL,
    event       VARCHAR(64) NOT NULL,
    status      VARCHAR(64) NOT NULL,
    reason      LONGTEXT NOT NULL,
    thought     LONGTEXT NOT NULL,
    prev_hash   CHAR(64) NOT NULL,
    hash        CHAR(64) NOT NULL,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY audit_entries_hash_uk (hash),
    CONSTRAINT audit_entries_idx_chk CHECK (idx >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX audit_entries_event_idx ON audit_entries (event);
CREATE INDEX audit_entries_created_at_idx ON audit_entries (created_at);

CREATE TABLE IF NOT EXISTS monthly_spend (
    account_id  VARCHAR(64) NOT NULL,
    `year_month` CHAR(7) NOT NULL,
    spent       DECIMAL(12, 2) NOT NULL DEFAULT 0,
    currency    CHAR(3) NOT NULL DEFAULT 'HKD',
    updated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (account_id, `year_month`),
    CONSTRAINT monthly_spend_spent_chk CHECK (spent >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS spend_ledger (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id      VARCHAR(64) NOT NULL,
    `year_month`    CHAR(7) NOT NULL,
    amount          DECIMAL(12, 2) NOT NULL,
    currency        CHAR(3) NOT NULL DEFAULT 'HKD',
    payment_id      VARCHAR(64),
    idempotency_key VARCHAR(128),
    note            VARCHAR(1024) NOT NULL DEFAULT '',
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY spend_ledger_idem_uk (account_id, idempotency_key),
    CONSTRAINT spend_ledger_amount_chk CHECK (amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX spend_ledger_account_ym_idx ON spend_ledger (account_id, `year_month`);

INSERT IGNORE INTO schema_migrations (id) VALUES ('001_initial');

CREATE TABLE IF NOT EXISTS accounts (
    id              VARCHAR(64) PRIMARY KEY,
    email           VARCHAR(255) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(80) NOT NULL,
    phone           VARCHAR(40) NOT NULL DEFAULT '',
    membership      VARCHAR(40) NOT NULL DEFAULT 'standard',
    marketing       BOOLEAN NOT NULL DEFAULT FALSE,
    monthly_cap     DECIMAL(12, 2) NOT NULL DEFAULT 2000,
    per_order_cap   DECIMAL(12, 2) NOT NULL DEFAULT 500,
    bulk_ceiling    DECIMAL(12, 2) NOT NULL DEFAULT 800,
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY accounts_email_uk (email),
    CONSTRAINT accounts_monthly_cap_chk CHECK (monthly_cap >= 0),
    CONSTRAINT accounts_per_order_cap_chk CHECK (per_order_cap >= 0),
    CONSTRAINT accounts_bulk_ceiling_chk CHECK (bulk_ceiling >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS addresses (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id  VARCHAR(64) NOT NULL,
    label       VARCHAR(40) NOT NULL DEFAULT 'Home',
    line1       VARCHAR(160) NOT NULL,
    line2       VARCHAR(160) NOT NULL DEFAULT '',
    district    VARCHAR(80) NOT NULL DEFAULT '',
    region      VARCHAR(80) NOT NULL DEFAULT '',
    fake        BOOLEAN NOT NULL DEFAULT TRUE,
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT addresses_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX addresses_account_idx ON addresses (account_id);

CREATE TABLE IF NOT EXISTS payment_methods (
    id          VARCHAR(64) PRIMARY KEY,
    account_id  VARCHAR(64) NOT NULL,
    route       VARCHAR(40) NOT NULL,
    label       VARCHAR(80) NOT NULL,
    last4       VARCHAR(4) NOT NULL DEFAULT '',
    connected   BOOLEAN NOT NULL DEFAULT TRUE,
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT payment_methods_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX payment_methods_account_idx ON payment_methods (account_id);

CREATE TABLE IF NOT EXISTS orders (
    id              VARCHAR(64) PRIMARY KEY,
    account_id      VARCHAR(64) NOT NULL,
    intent          TEXT NOT NULL,
    status          VARCHAR(40) NOT NULL,
    step            VARCHAR(64) NOT NULL DEFAULT '',
    amount          DECIMAL(12, 2),
    currency        CHAR(3) NOT NULL DEFAULT 'HKD',
    merchant        VARCHAR(80) NOT NULL DEFAULT '',
    payment_route   VARCHAR(40) NOT NULL DEFAULT '',
    payment_id      VARCHAR(64),
    escalation_id   VARCHAR(64),
    snapshot        JSON NOT NULL,
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT orders_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX orders_account_created_idx ON orders (account_id, created_at);
CREATE INDEX orders_account_status_idx ON orders (account_id, status);

CREATE TABLE IF NOT EXISTS order_lines (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id    VARCHAR(64) NOT NULL,
    sku         VARCHAR(64) NOT NULL,
    name        VARCHAR(255) NOT NULL DEFAULT '',
    merchant    VARCHAR(80) NOT NULL DEFAULT '',
    category    VARCHAR(80) NOT NULL DEFAULT '',
    qty         INTEGER NOT NULL,
    unit_price  DECIMAL(12, 2) NOT NULL DEFAULT 0,
    line_total  DECIMAL(12, 2) NOT NULL DEFAULT 0,
    CONSTRAINT order_lines_qty_chk CHECK (qty > 0),
    CONSTRAINT order_lines_order_fk FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX order_lines_order_idx ON order_lines (order_id);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id    VARCHAR(64) NOT NULL,
    step        VARCHAR(64) NOT NULL,
    status      VARCHAR(40) NOT NULL,
    snapshot    JSON NOT NULL,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT workflow_checkpoints_order_fk FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX workflow_checkpoints_order_idx ON workflow_checkpoints (order_id, created_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id  VARCHAR(64) NOT NULL,
    order_id    VARCHAR(64),
    role        VARCHAR(16) NOT NULL,
    content     TEXT NOT NULL,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT chat_messages_role_chk CHECK (role IN ('user', 'assistant')),
    CONSTRAINT chat_messages_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE,
    CONSTRAINT chat_messages_order_fk FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX chat_messages_account_idx ON chat_messages (account_id, created_at);

CREATE TABLE IF NOT EXISTS agent_runs (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id  VARCHAR(64) NOT NULL,
    order_id    VARCHAR(64),
    intent      TEXT NOT NULL,
    status      VARCHAR(40) NOT NULL,
    step        VARCHAR(64) NOT NULL DEFAULT '',
    summary     VARCHAR(512) NOT NULL DEFAULT '',
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY agent_runs_order_uk (order_id),
    CONSTRAINT agent_runs_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE,
    CONSTRAINT agent_runs_order_fk FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX agent_runs_account_idx ON agent_runs (account_id, created_at);

CREATE TABLE IF NOT EXISTS recurrent_tasks (
    id              VARCHAR(64) PRIMARY KEY,
    account_id      VARCHAR(64) NOT NULL,
    intent          TEXT NOT NULL,
    cadence         VARCHAR(16) NOT NULL DEFAULT 'monthly',
    next_run        DATETIME(6) NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    last_order_id   VARCHAR(64),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT recurrent_tasks_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX recurrent_tasks_account_idx ON recurrent_tasks (account_id);

INSERT IGNORE INTO schema_migrations (id) VALUES ('002_profile_orders');

-- Shop shelf. hk_products_full.json loads here. /demo/reset does not touch it.
CREATE TABLE IF NOT EXISTS catalog_products (
    id           VARCHAR(32) PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    price        DECIMAL(12, 2) NOT NULL,
    currency     CHAR(3) NOT NULL DEFAULT 'HKD',
    merchant     VARCHAR(80) NOT NULL,
    category     VARCHAR(80) NOT NULL,
    stock        INTEGER NULL,
    in_stock     BOOLEAN NOT NULL DEFAULT TRUE,
    image_url    VARCHAR(512),
    sell_point   VARCHAR(128) NOT NULL DEFAULT '',
    product_url  VARCHAR(1024),
    updated_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT catalog_products_price_chk CHECK (price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX catalog_products_merchant_idx ON catalog_products (merchant);
CREATE INDEX catalog_products_category_idx ON catalog_products (category);

INSERT IGNORE INTO schema_migrations (id) VALUES ('003_catalog_products');

-- Payment control loop. Owned by the payment service on port 8004.
-- The JWT stays on the server. Card numbers and CVV are never stored.
CREATE TABLE IF NOT EXISTS payments (
    payment_id        VARCHAR(64) PRIMARY KEY,
    status            VARCHAR(16) NOT NULL,
    account_id        VARCHAR(64) NOT NULL,
    amount            DECIMAL(12, 2) NOT NULL,
    currency          CHAR(3) NOT NULL DEFAULT 'HKD',
    merchant          VARCHAR(80) NOT NULL,
    rail              VARCHAR(32) NOT NULL,
    purpose           VARCHAR(255) NOT NULL DEFAULT '',
    intent            TEXT NOT NULL,
    cart_hash         VARCHAR(64) NOT NULL DEFAULT '',
    token_jti         VARCHAR(64) NOT NULL,
    token             TEXT NOT NULL,
    token_expires_at  BIGINT NOT NULL,
    recommendation    JSON NULL,
    auth_id           VARCHAR(64) NULL,
    order_id          VARCHAR(64) NULL,
    receipt_id        VARCHAR(64) NULL,
    error             VARCHAR(255) NULL,
    evidence          JSON NOT NULL,
    extra             JSON NOT NULL,
    created_at        VARCHAR(40) NOT NULL,
    updated_at        VARCHAR(40) NOT NULL,
    CONSTRAINT payments_amount_chk CHECK (amount > 0),
    CONSTRAINT payments_status_chk CHECK (
        status IN ('DRAFT', 'PENDING', 'AUTHORIZED', 'CAPTURED', 'FAILED', 'REFUNDED')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX payments_account_created_idx ON payments (account_id, created_at);
CREATE INDEX payments_token_jti_idx ON payments (token_jti);

CREATE TABLE IF NOT EXISTS payment_jti (
    jti         VARCHAR(64) PRIMARY KEY,
    payment_id  VARCHAR(64) NULL,
    used_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (id) VALUES ('004_payments');

-- Shopper benefit ranking and the points earned when an order is approved.
CREATE TABLE IF NOT EXISTS account_preferences (
    account_id    VARCHAR(64) PRIMARY KEY,
    benefit_rank  JSON NOT NULL,
    CONSTRAINT account_preferences_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS benefit_balances (
    account_id  VARCHAR(64) NOT NULL,
    kind        VARCHAR(40) NOT NULL,
    amount      DECIMAL(14, 2) NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, kind),
    CONSTRAINT benefit_balances_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS benefit_ledger (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id  VARCHAR(64) NOT NULL,
    order_id    VARCHAR(64) NULL,
    kind        VARCHAR(40) NOT NULL,
    amount      DECIMAL(14, 2) NOT NULL,
    note        VARCHAR(255) NOT NULL DEFAULT '',
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT benefit_ledger_account_fk FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX benefit_ledger_account_idx ON benefit_ledger (account_id);

INSERT IGNORE INTO schema_migrations (id) VALUES ('005_benefits');

-- Policy verdicts per account (written by backend-policy :8001 on /check_policy
-- and /create_escalation when the caller sends account_id). The hash-chained
-- audit ledger has no account id, so the dashboard reads failures from here.
CREATE TABLE IF NOT EXISTS policy_decisions (
    id             VARCHAR(32) PRIMARY KEY,
    ts             VARCHAR(32) NOT NULL,
    account_id     VARCHAR(64) NOT NULL,
    run_id         VARCHAR(64) NOT NULL DEFAULT '',
    stage          VARCHAR(32) NOT NULL DEFAULT '',
    kind           VARCHAR(16) NOT NULL DEFAULT 'check',
    status         VARCHAR(16) NOT NULL,
    rule           VARCHAR(64) NOT NULL DEFAULT '',
    reason         VARCHAR(512) NOT NULL DEFAULT '',
    amount         DECIMAL(12, 2) NOT NULL DEFAULT 0,
    merchant       VARCHAR(80) NOT NULL DEFAULT '',
    category       VARCHAR(80) NOT NULL DEFAULT '',
    sku            VARCHAR(64) NOT NULL DEFAULT '',
    qty            INTEGER NOT NULL DEFAULT 1,
    escalation_id  VARCHAR(64) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX policy_decisions_account_idx ON policy_decisions (account_id, ts);

INSERT IGNORE INTO schema_migrations (id) VALUES ('006_policy_decisions');


CREATE TABLE IF NOT EXISTS market_rules (
    id INTEGER PRIMARY KEY,
    version BIGINT NOT NULL,
    rules_json JSON NOT NULL,
    updated_by VARCHAR(64) NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO schema_migrations (id) VALUES ('007_market_rules');
