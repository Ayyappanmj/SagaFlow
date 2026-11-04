"""In-process benchmark of the saga core (SQLite + in-memory broker, single thread, real clock).
Measures order-creation latency and end-to-end saga completion throughput. This does NOT measure
PostgreSQL / RabbitMQ / HTTP -- use benchmarks/locustfile.py against the Docker stack for that.
Usage: PYTHONPATH=backend python benchmarks/bench_core.py [N]"""
import platform
import statistics
import sys
import tempfile
import time

from inventory_service.service import InventoryService
from orchestrator.engine import SagaEngine
from orchestrator.orders import create_order
from orchestrator.runtime import OrchestratorRuntime
from payment_service.service import PaymentService
from shared.broker import InMemoryBroker
from shared.consumer import Consumer
from shared.db import Database
from shared.migrate import apply_migrations
from shared.outbox import OutboxPublisher
from shipping_service.service import ShippingService

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
d = tempfile.mkdtemp()
dbs = {n: Database(f"sqlite:///{d}/{n}.db") for n in ("orchestrator", "inventory", "payment", "shipping")}
for n, db in dbs.items():
    apply_migrations(db, n)
broker = InMemoryBroker()
eng = SagaEngine(dbs["orchestrator"])
inv, pay, shp = InventoryService(dbs["inventory"]), PaymentService(dbs["payment"]), ShippingService(dbs["shipping"])
inv.seed({"WIDGET": N * 2})
rt = OrchestratorRuntime(eng, broker)
pubs = [rt.publisher] + [OutboxPublisher(s.db, broker, service=s.name) for s in (inv, pay, shp)]
cons = [rt.consumer] + [Consumer(broker, f"{s.name}.commands", s.handle, name=s.name) for s in (inv, pay, shp)]

lat = []
t0 = time.perf_counter()
for i in range(N):
    t = time.perf_counter()
    req = {"customer_ref": "b", "items": [{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 100}]}
    create_order(dbs["orchestrator"], eng, req, f"bench-{i:06d}", "c")
    lat.append((time.perf_counter() - t) * 1000)
t_create = time.perf_counter() - t0
t1 = time.perf_counter()
msgs = 0
while True:
    p = sum(x.relay_once(200) for x in pubs)
    c = 0
    for k in cons:
        while k.poll_once():
            c += 1
    msgs += c
    if p == 0 and c == 0:
        break
t_run = time.perf_counter() - t1
with dbs["orchestrator"].read() as tx:
    done = tx.one("SELECT COUNT(*) AS n FROM sagas WHERE state='COMPLETED'")["n"]
lat.sort()


def q(p):
    return lat[min(len(lat) - 1, int(len(lat) * p))]


print(f"machine: {platform.platform()} python {platform.python_version()} cpus-bound-single-thread")
print(f"workload: {N} orders, 3-step saga, SQLite (WAL) + in-memory broker, single thread")
print(f"order creation latency ms: p50={q(.5):.2f} p95={q(.95):.2f} p99={q(.99):.2f} mean={statistics.mean(lat):.2f}")
print(
    f"saga completion: {done}/{N} completed in {t_run:.2f}s => {done / t_run:.1f} sagas/s; "
    f"messages processed {msgs} => {msgs / t_run:.0f} msg/s"
)
