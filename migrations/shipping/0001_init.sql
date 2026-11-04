CREATE TABLE shipments (
    id              TEXT PRIMARY KEY,
    saga_id         TEXT NOT NULL UNIQUE,
    order_id        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('CREATED','CANCELLED','SHIPPED')),
    tracking_number TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
