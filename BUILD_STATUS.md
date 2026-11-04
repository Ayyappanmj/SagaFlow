# BUILD_STATUS

Current execution environment: Windows 11 Home Single Language, Python 3.11.9, Node.js v24.12.0, npm 11.20.0, Intel(R) Core(TM) i3-1005G1 CPU @ 1.20GHz (2 cores, 4 threads), 8 GB RAM. Run mode: **Local multi-process execution (without Docker)**.

---

## 1. Commands Actually Executed & Verified

| Command | Purpose | Result |
|---|---|---|
| `cd backend && python -m unittest discover -s tests -t .` | Baseline test suite execution | **51 tests collected: 51 passed** (fixed 1 bug in `api/app.py:recover`) |
| `pip install -r backend/requirements-dev.txt` | Install development dependencies | **Installed cleanly** (FastAPI, pytest, httpx, ruff, pydantic, psycopg, pika) |
| `ruff check backend scripts benchmarks` | Linting & code quality verification | **Clean: All checks passed!** (fixed 47 lint issues across 20 files) |
| `python -m pytest backend/tests/ -v` | Comprehensive pytest suite | **59 collected: 54 passed, 5 skipped** (integration tests skip locally when PG/MQ containers are absent) |
| `cd frontend && npm.cmd install && npm.cmd run build` | TypeScript type-check and Vite production build | **Clean build: 0 TypeScript errors, dist/ assets generated** |
| `python -m seed` | Seed inventory database | **Success: Seeded 100,000 DOOHICKEY and 1,000 WIDGET units** |
| `python scripts/run_local.py` | Multi-process runner for all 5 microservices | **All 5 microservices live & healthy** (ports 8000, 8001, 8002, 8003, 8010) |
| `curl http://127.0.0.1:8000/api/v1/system-health` | Microservice health aggregation check | **All services report `up: true`, `ready: true`, checks OK** |
| `python scripts/smoke.py` | End-to-end integration smoke test | **Happy path -> COMPLETED; Shipping failure -> COMPENSATED** |
| `cd frontend && npm.cmd run dev` | Launch Vite frontend dev server | **Live on http://localhost:3000** |
| `locust -f benchmarks/locustfile.py --headless ...` | Headless Locust benchmarks at 10, 25, 50 users | **Completed with 0.00% error rate** (filled into `benchmarks/REPORT.md`) |
| `node scripts/capture_assets.js` | Headless Edge screenshot capture | **Generated 6 high-res screenshots in docs/images/** |
| `python scripts/build_demo_gif.py` | Stitch demo frames into animated GIF | **Generated docs/images/demo.gif (11 steps, 814 KB)** |

---

## 2. Test Suite Breakdown

### Unit, DB, Messaging, E2E, and API Tests (`backend/tests/`)
| Test File | Tests Run | Result | Notes |
|---|---|---|---|
| `test_unit.py` | 11 | **11 Passed** | State machine transitions, optimistic locking, retry backoff calculation |
| `test_db_integration.py` | 6 | **6 Passed** | SQLite schema migrations, transactional outbox insert/claim, rollback semantics |
| `test_messaging.py` | 11 | **11 Passed** | In-memory broker, bounded retry DLQ, SQLiteBroker inter-process delivery |
| `test_e2e.py` | 21 | **21 Passed** | Forward order flow, shipping compensation, compensation failure quarantine (`REQUIRES_ATTENTION`), operator manual retry, duplicate message deduplication |
| `test_api.py` | 5 | **5 Passed** | Order creation, saga history retrieval, dev fault injection endpoints, admin token auth, recovery rejection HTTP 409 |

### Infrastructure Integration Suite (`backend/tests/integration/`)
| Test File | Local Result | CI Result (with PG + MQ containers) |
|---|---|---|
| `test_postgres_concurrency.py` | Skipped (No live Postgres) | Runs in CI: 8 concurrent threads reserving 4 units against 5 stock with row locks (`SELECT FOR UPDATE`) |
| `test_rabbitmq_guarantees.py` | Skipped (No live RabbitMQ) | Runs in CI: Outbox publisher confirms, poison message routing to `.dlq`, outbox durability during broker downtime |
| `test_crash_recovery.py` | Skipped (No live Postgres/MQ) | Runs in CI: Mid-saga orchestrator SIGKILL, restart, recovery, asserting zero duplicate payments or stock deductions |

**Total Suite: 59 collected — 54 passed, 5 skipped (0 failed).**

---

## 3. Defects Found & Resolved

1. **Defect:** `POST /api/v1/sagas/{id}/recover` returned HTTP 200 instead of HTTP 409 when no in-flight step was eligible for recovery.
   - **Root Cause:** `backend/api/app.py` called `engine.recover(saga_id)` but ignored its boolean return value.
   - **Fix:** Added check `if not ok: raise HTTPException(status_code=409, detail="no in-flight operation eligible for recovery")`.
2. **Defect:** 47 Ruff lint errors across 20 files (line lengths > 130 chars, unformatted imports, lambda assignments, unused exception variables, B039 ContextVar mutable dict default).
   - **Fix:** Fixed all formatting, refactored ContextVar initialization, and formatted imports. `ruff check` now passes cleanly.
3. **Defect:** Windows IPv6 latency penalty causing `system-health` endpoint to take 9+ seconds.
   - **Root Cause:** Node/Python HTTP clients on Windows attempted IPv6 `[::1]` first with a 2-second timeout before falling back to IPv4 `127.0.0.1`.
   - **Fix:** Configured internal service base URLs to `http://127.0.0.1:<port>` and parallelized dependency checks via `asyncio.gather`. Duration dropped to 1.2s.
4. **Defect:** Background microservices killed when spawned as CLI subprocesses.
   - **Root Cause:** PowerShell CLI subprocesses detached prematurely in Windows.
   - **Fix:** Rewrote `scripts/run_local.py` using Python `multiprocessing.Process` invoking `uvicorn.run()` directly, enabling clean process tree management and graceful shutdown.
5. **Defect:** Multi-process coordination without Docker / RabbitMQ.
   - **Fix:** Implemented `SQLiteBroker` conforming to the exact broker interface, enabling inter-process message passing via atomic SQLite transactions with WAL mode. Added 3 unit tests in `test_messaging.py`.

---

## 4. Benchmark Summary (Local Physical Laptop)

Full report: [benchmarks/REPORT.md](benchmarks/REPORT.md).
- **Environment:** Intel Core i3-1005G1 CPU @ 1.20GHz (2 cores, 4 threads), 8 GB RAM, Windows 11, Python 3.11.9, SQLite WAL mode.
- **Duration:** 60 seconds per concurrency tier with headless Locust.
- **Results:**
  - **10 users:** 546 requests, **7.21 orders/s**, p50: 190 ms, p95: 4,700 ms, p99: 11,000 ms, **0.00% errors**.
  - **25 users:** 922 requests, **11.28 orders/s**, p50: 160 ms, p95: 9,400 ms, p99: 21,000 ms, **0.00% errors**.
  - **50 users:** 1,032 requests, **13.16 orders/s**, p50: 300 ms, p95: 6,400 ms, p99: 31,000 ms, **0.00% errors**.
- **Identified Bottleneck:** Dual-core CPU scheduling and SQLite single-writer table locks during high write concurrency.

---

## 5. Artifacts Generated

- Real screenshots: `docs/images/overview.png`, `docs/images/system_health.png`, `docs/images/orders_simulation.png`, `docs/images/saga_timeline_compensated.png`, `docs/images/requires_attention_before.png`, `docs/images/requires_attention_after.png`.
- Real animated demo walkthrough: `docs/images/demo.gif` (11 slides, 814 KB).
- Benchmark results & raw CSVs: `benchmarks/REPORT.md`, `benchmarks/results/locust_*`.
