# Testing
Run from the repo root: `sh scripts/run_tests.sh [unit|db|messaging|e2e|api|all]` or `python -m pytest`.

| Layer | File | Dependencies |
|---|---|---|
| Unit (state machine, compensation plan, retry, schema) | `test_unit.py` | none |
| DB integration (concurrent reservations, rollback, outbox atomicity, constraints, optimistic locking) | `test_db_integration.py` | real SQL (SQLite file) |
| Messaging (relay, broker outage, duplicates, ack-after-commit, retries, DLQ) | `test_messaging.py` | in-memory broker |
| End-to-end (happy path, all failure scenarios, compensation failure, restart/recovery, duplicates, concurrency) | `test_e2e.py` | SQLite + in-memory broker |
| API (validation, 404/409, idempotency, admin/dev protection, health/metrics) | `test_api.py` | needs `fastapi`+`httpx`; skipped otherwise |

**Honest scope:** the suite runs against SQLite and an in-memory broker with the same SQL and the same engine code. It does **not** exercise PostgreSQL row-locking semantics or a real RabbitMQ; those adapters (`psycopg` path in `shared/db.py`, `RabbitMQBroker`) are implemented but need running on a machine with Docker (`docker compose up`, then `python scripts/smoke.py`). SQLite serializes writers, so the concurrency test proves the conditional-update logic, not PostgreSQL's lock behaviour.
