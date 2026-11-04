# Benchmark report (template — fill in from a real run; do not invent numbers)

| Field | Value |
|---|---|
| Date | |
| Machine (CPU / RAM / disk) | |
| OS / Docker version | |
| Python / PostgreSQL / RabbitMQ versions | |
| Warm-up (duration, requests) | |
| Test duration | |
| Workload (mix, SKUs, stock) | |
| Concurrency (users / spawn rate) | |

## Results
| Metric | Result |
|---|---|
| Order creation latency p50 / p95 / p99 (ms) | |
| Workflow completion time p50 / p95 (s) — Grafana `sagaflow_workflow_duration_seconds` | |
| Saga throughput (completed/s) | |
| Message throughput (msg/s) | |
| API error rate (%) | |
| CPU / memory (`docker stats`) | |

## Known bottlenecks observed
-
