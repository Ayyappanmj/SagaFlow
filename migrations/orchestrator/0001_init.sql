CREATE TABLE orders (
    id              TEXT PRIMARY KEY,
    customer_ref    TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETED','CANCELLED','FAILED','REQUIRES_ATTENTION')),
    total_cents     INTEGER NOT NULL CHECK (total_cents >= 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE order_items (
    id               TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL REFERENCES orders(id),
    sku              TEXT NOT NULL,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0)
);
CREATE INDEX ix_order_items_order ON order_items(order_id);

CREATE TABLE sagas (
    id               TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL UNIQUE REFERENCES orders(id),
    state            TEXT NOT NULL CHECK (state IN
        ('PENDING','RUNNING','COMPLETED','COMPENSATING','COMPENSATED','FAILED','REQUIRES_ATTENTION')),
    current_step     TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    error_code       TEXT,
    error_detail     TEXT,
    correlation_id   TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    simulate_json    TEXT NOT NULL DEFAULT '{}',
    version          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT
);
CREATE INDEX ix_sagas_state_updated ON sagas(state, updated_at);
CREATE INDEX ix_sagas_created ON sagas(created_at, id);

CREATE TABLE saga_steps (
    saga_id             TEXT NOT NULL REFERENCES sagas(id),
    step_name           TEXT NOT NULL,
    ordinal             INTEGER NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('PENDING','DISPATCHED','COMPLETED','FAILED','UNKNOWN')),
    compensation_status TEXT NOT NULL DEFAULT 'NONE' CHECK (compensation_status IN
        ('NONE','PENDING','DISPATCHED','COMPLETED','FAILED','NOT_REQUIRED')),
    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL,
    comp_attempts       INTEGER NOT NULL DEFAULT 0,
    comp_max_attempts   INTEGER NOT NULL,
    last_error          TEXT,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (saga_id, step_name)
);

CREATE TABLE saga_events (
    id                  TEXT PRIMARY KEY,
    seq                 INTEGER NOT NULL,
    saga_id             TEXT NOT NULL REFERENCES sagas(id),
    step_name           TEXT,
    previous_state      TEXT,
    new_state           TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    attempt             INTEGER NOT NULL DEFAULT 0,
    error_detail        TEXT,
    compensation_status TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (saga_id, seq)
);

CREATE TABLE idempotency_records (
    key           TEXT PRIMARY KEY,
    request_hash  TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
