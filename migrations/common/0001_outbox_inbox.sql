-- Present in every service database: transactional outbox + processed-message (inbox) table.
CREATE TABLE outbox_events (
    id             TEXT PRIMARY KEY,
    destination    TEXT NOT NULL,
    message_type   TEXT NOT NULL,
    saga_id        TEXT,
    correlation_id TEXT,
    body           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PUBLISHED')),
    attempts       INTEGER NOT NULL DEFAULT 0,
    publish_copies INTEGER NOT NULL DEFAULT 1,
    available_at   TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    published_at   TEXT,
    last_error     TEXT
);
CREATE INDEX ix_outbox_pending ON outbox_events (status, available_at);
CREATE INDEX ix_outbox_saga ON outbox_events (saga_id, status);

CREATE TABLE processed_messages (
    message_id   TEXT NOT NULL,
    consumer     TEXT NOT NULL,
    result_json  TEXT,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (message_id, consumer)
);
