# Benchmarking
- **Core (no Docker):** `PYTHONPATH=backend python benchmarks/bench_core.py 300` — single-thread SQLite + in-memory broker; measures order creation latency and saga throughput of the engine itself.
- **Full stack:** `docker compose up -d`, seed, then `locust -f benchmarks/locustfile.py --host http://localhost:8000`. Watch Grafana (`sagaflow_workflow_duration_seconds`, HTTP latency p95) and `docker stats`.
- Fill in `benchmarks/REPORT_TEMPLATE.md` from your own runs. The only recorded numbers in this repo are in `benchmarks/results/bench_core_sandbox.txt`, from the build sandbox (1 vCPU); they say nothing about PostgreSQL/RabbitMQ performance.
