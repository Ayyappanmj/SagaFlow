# BUILD_STATUS

Build environment: Linux sandbox, Python 3.12.3, **no network, no Docker, no PostgreSQL, no RabbitMQ, no FastAPI/pytest/psycopg/pika installed**.

## Implemented
- **Executed & tested here:** saga state machine, engine (forward flow, retries/backoff, reverse-order compensation, unknown outcomes, manual retry/recover, stale recovery, optimistic locking), transactional outbox + relay, idempotent consumers, DLQ/bounded retry consumer, inventory/payment/shipping services, order idempotency, failure injection, SQL migrations, metrics registry, benchmark script.
- **Written, NOT executed here:** `RabbitMQBroker` (pika), PostgreSQL path of `shared/db.py` (psycopg), FastAPI apps (`api/app.py`, service `main.py`s, `shared/app_factory.py`), React dashboard (`frontend/`), Dockerfiles, `docker-compose.yml`, Prometheus/Grafana config, GitHub Actions workflow, Locust file, PowerShell script. Only syntax/parse-checked (`py_compile`, YAML/JSON parse).

## Tests actually executed (`cd backend && python -m unittest discover -s tests -t .`)
| File | Result |
|---|---|
| test_unit.py | 11 ran, 11 passed |
| test_db_integration.py | 6 ran, 6 passed |
| test_messaging.py | 8 ran, 8 passed |
| test_e2e.py | 21 ran, 21 passed |
| test_api.py | 5 **skipped** (fastapi/httpx not installed) |
**Total: 51 collected — 46 passed, 0 failed, 5 skipped.** One real defect was found and fixed during the run (fault-injection `drop_reply_once` hit every service; now targets named services).

## Not executed
API tests · anything needing PostgreSQL/RabbitMQ (incl. true PostgreSQL row-lock concurrency; the concurrency test ran on SQLite) · Docker Compose startup · frontend `npm install/build` · Ruff · Locust benchmark · CI workflow · Grafana dashboard rendering. Expect possible small defects in these layers on first run.

## Benchmark actually run
`benchmarks/results/bench_core_sandbox.txt` (SQLite + in-memory broker, 1 vCPU): order creation p50 1.23 ms, p95 2.14 ms; 300/300 sagas completed at ~132 sagas/s. Not representative of the Docker stack.

## Known bugs / incomplete
- `test_crash_between_publish_and_mark…` simulates the duplicate by publishing manually before the relay (not by killing the relay mid-transaction).
- Dead-letter page depends on broker `basic_get`+requeue peeking (RabbitMQ adapter, untested).
- No Alembic/SQLAlchemy (documented deviation). Screenshots not included.

## Startup
`cp .env.example .env && docker compose up --build -d && sh scripts/seed.sh && python scripts/smoke.py` — dashboard http://localhost:3000, API docs http://localhost:8000/docs.
No-Docker core check: `cd backend && python -m unittest discover -s tests -t .`
