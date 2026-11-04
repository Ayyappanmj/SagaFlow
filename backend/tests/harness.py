"""Test harness: real SQL schemas (SQLite files), in-memory broker, deterministic FakeClock."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest

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
from shared.retry import RetryPolicy
from shared.timeutil import FakeClock
from shipping_service.service import ShippingService


class Env:
    def __init__(self, stock=None, policy=None):
        self.dir = tempfile.mkdtemp(prefix="sagaflow-test-")
        self.clock = FakeClock()
        self.policy = policy or RetryPolicy(max_attempts=3, base_delay_s=1.0)
        self.broker = InMemoryBroker()
        self.dbs = {}
        for name in ("orchestrator", "inventory", "payment", "shipping"):
            db = Database(f"sqlite:///{self.dir}/{name}.db")
            apply_migrations(db, name)
            self.dbs[name] = db
        self.build()
        self.inventory.seed(stock or {"WIDGET": 10, "GADGET": 5})

    def build(self):
        """(Re)create all in-process components against the SAME databases = a process restart."""
        c = self.clock
        self.engine = SagaEngine(self.dbs["orchestrator"], self.policy, c)
        self.inventory = InventoryService(self.dbs["inventory"], c)
        self.payment = PaymentService(self.dbs["payment"], c)
        self.shipping = ShippingService(self.dbs["shipping"], c)
        self.runtime = OrchestratorRuntime(self.engine, self.broker, stale_after_s=60)
        self.publishers = [self.runtime.publisher] + [
            OutboxPublisher(s.db, self.broker, c, service=s.name) for s in (self.inventory, self.payment, self.shipping)]
        self.consumers = [self.runtime.consumer] + [
            Consumer(self.broker, f"{s.name}.commands", s.handle, max_attempts=3, name=s.name)
            for s in (self.inventory, self.payment, self.shipping)]

    def restart(self):
        self.broker.requeue_unacked()
        self.build()

    def order(self, items=None, key=None, simulate=None, customer="c1"):
        items = items or [{"sku": "WIDGET", "quantity": 2, "unit_price_cents": 1000}]
        key = key or f"key-{len(items)}-{id(items)}-{self.clock.now_iso()}"
        return create_order(self.dbs["orchestrator"], self.engine,
                            {"customer_ref": customer, "items": items}, key, "corr-1", simulate)

    def pump(self, max_rounds=200, auto_advance=True, skip=()):
        """Run relays + consumers until quiet. Advances the fake clock to the next delayed outbox row."""
        for _ in range(max_rounds):
            progress = 0
            for p in self.publishers:
                progress += p.relay_once()
            for c in self.consumers:
                if c.name in skip:
                    continue
                while c.poll_once():
                    progress += 1
            if progress == 0:
                if auto_advance and self._advance_to_next_delayed():
                    continue
                return
        raise AssertionError("pump did not quiesce")

    def _advance_to_next_delayed(self) -> bool:
        from shared.timeutil import iso, parse
        nxt = None
        for p in self.publishers:
            with p.db.read() as tx:
                r = tx.one("SELECT MIN(available_at) AS t FROM outbox_events WHERE status='PENDING'")
            if r and r["t"] and (nxt is None or r["t"] < nxt):
                nxt = r["t"]
        if nxt and nxt > iso(self.clock.now()):
            self.clock.set(parse(nxt))
            return True
        return False

    def saga(self, saga_id):
        from orchestrator.queries import get_saga
        return get_saga(self.dbs["orchestrator"], saga_id)

    def events(self, saga_id):
        from orchestrator.queries import get_history
        return [e["event_type"] for e in get_history(self.dbs["orchestrator"], saga_id)]

    def stock(self, sku="WIDGET"):
        with self.dbs["inventory"].read() as tx:
            return tx.one("SELECT available, reserved FROM inventory WHERE sku=?", (sku,))

    def rows(self, svc, sql, params=()):
        with self.dbs[svc].read() as tx:
            return tx.all(sql, params)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class SagaTestCase(unittest.TestCase):
    stock = None

    def setUp(self):
        self.env = Env(self.stock)
        self.addCleanup(self.env.cleanup)
