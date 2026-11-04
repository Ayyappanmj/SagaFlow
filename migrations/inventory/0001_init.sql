CREATE TABLE inventory (
    sku        TEXT PRIMARY KEY,
    available  INTEGER NOT NULL CHECK (available >= 0),
    reserved   INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE inventory_reservations (
    id         TEXT PRIMARY KEY,
    saga_id    TEXT NOT NULL UNIQUE,
    order_id   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('RESERVED','RELEASED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE reservation_items (
    reservation_id TEXT NOT NULL REFERENCES inventory_reservations(id),
    sku            TEXT NOT NULL REFERENCES inventory(sku),
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (reservation_id, sku)
);
