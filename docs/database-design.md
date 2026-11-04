# Database design

One PostgreSQL database per service. Migrations live in `migrations/` (`common/` for outbox+inbox, then per service); a tiny runner records versions in `schema_migrations`. Services apply migrations at startup; `python scripts/migrate.py` does it manually.

| DB | Tables |
|---|---|
| orchestrator | `orders`, `order_items`, `sagas`, `saga_steps`, `saga_events`, `idempotency_records`, `outbox_events`, `processed_messages` |
| inventory | `inventory`, `inventory_reservations`, `reservation_items`, `outbox_events`, `processed_messages` |
| payment | `payments`, `payment_operations`, `outbox_events`, `processed_messages` |
| shipping | `shipments`, `outbox_events`, `processed_messages` |

Key decisions
- **Overselling guard:** `UPDATE inventory SET available = available - :q WHERE sku = :s AND available >= :q`. PostgreSQL row-locks the row; a concurrent updater re-evaluates the predicate after the first commits, so two "4 of 5" requests cannot both win. `CHECK (available >= 0)` is a backstop.
- **Idempotency by constraint:** `UNIQUE(saga_id)` on reservations/payments/shipments, `UNIQUE(idempotency_key)` on orders/sagas/payment operations, `PRIMARY KEY(message_id, consumer)` on `processed_messages`.
- **Optimistic concurrency:** `sagas.version` incremented on every update (`WHERE id=? AND version=?`).
- **Timestamps:** ISO-8601 UTC strings (`...Z`) in `TEXT` columns so identical DDL runs on SQLite (tests) and PostgreSQL; they sort lexicographically. (Native `timestamptz` would be preferable in a PostgreSQL-only project.)
- **Pagination:** `ORDER BY created_at DESC, id LIMIT/OFFSET` with indexes on `(state, updated_at)` and `(created_at, id)`; keyset pagination would scale better.
- **Indexes:** `outbox_events(status, available_at)` for the relay; `outbox_events(saga_id, status)` for recovery.
