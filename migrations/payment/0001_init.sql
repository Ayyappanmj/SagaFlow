CREATE TABLE payments (
    id           TEXT PRIMARY KEY,
    saga_id      TEXT NOT NULL UNIQUE,
    order_id     TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    status       TEXT NOT NULL CHECK (status IN ('AUTHORIZED','DECLINED','VOIDED')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE payment_operations (
    id              TEXT PRIMARY KEY,
    payment_id      TEXT NOT NULL REFERENCES payments(id),
    op_type         TEXT NOT NULL CHECK (op_type IN ('AUTHORIZE','DECLINE','VOID')),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL
);
