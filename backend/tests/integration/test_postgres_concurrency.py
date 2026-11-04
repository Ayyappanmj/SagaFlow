"""Integration test: true PostgreSQL row-level locks under concurrency.

Requirement: 8 concurrent reservations of 4 units against stock of 5 -> exactly one succeeds.
"""
from __future__ import annotations

import threading
import unittest
import uuid

from inventory_service.service import InventoryService
from shared.db import Database
from shared.messages import Envelope
from tests.integration.infra import HAVE_PG, init_pg_service, pg_url


def make_reservation_env(saga_id: str, sku: str, qty: int) -> Envelope:
    return Envelope(
        type="inventory.reserve",
        saga_id=saga_id,
        correlation_id=str(uuid.uuid4()),
        idempotency_key=f"{saga_id}:RESERVE_INVENTORY:forward",
        payload={
            "order_id": f"order-{saga_id}",
            "step": "RESERVE_INVENTORY",
            "action": "forward",
            "attempt": 1,
            "items": [{"sku": sku, "quantity": qty}],
            "simulate": {},
        },
    )


@unittest.skipUnless(HAVE_PG, "Real PostgreSQL instance required (set POSTGRES_* or run in CI)")
class PostgresRowLockConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.db = init_pg_service("inventory")
        self.sku = f"LOCK_TEST_{uuid.uuid4().hex[:8]}"
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM outbox_events WHERE destination='orchestrator.replies'")
            tx.execute(
                "INSERT INTO inventory(sku, available, reserved, updated_at) VALUES (?, 5, 0, NOW())",
                (self.sku,),
            )

    def tearDown(self):
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM inventory WHERE sku=?", (self.sku,))

    def test_8_concurrent_reservations_of_4_against_5_stock(self):
        errors: list[Exception] = []

        def worker(thread_idx: int):
            try:
                # Each worker gets an independent connection to PostgreSQL to test true inter-connection row locks
                worker_db = Database(pg_url("inventory"))
                svc = InventoryService(worker_db)
                env = make_reservation_env(f"pg-saga-{self.sku}-{thread_idx}", self.sku, 4)
                svc.handle(env)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Unexpected worker exceptions: {errors}")

        with self.db.read() as tx:
            stock = tx.one("SELECT available, reserved FROM inventory WHERE sku=?", (self.sku,))
            reservations = tx.all(
                "SELECT id, status FROM inventory_reservations WHERE id IN ("
                "SELECT reservation_id FROM reservation_items WHERE sku=?)",
                (self.sku,),
            )
            replies = tx.all(
                "SELECT body FROM outbox_events WHERE destination='orchestrator.replies' AND body LIKE ?",
                (f"%{self.sku}%",),
            )

        self.assertIsNotNone(stock)
        self.assertEqual(stock["available"], 1, "Available stock must be exactly 1 (5 - 4)")
        self.assertEqual(stock["reserved"], 4, "Reserved stock must be exactly 4")
        self.assertEqual(len(reservations), 1, "Exactly one reservation row must exist")

        succeeded = sum('"status":"SUCCEEDED"' in r["body"] for r in replies)
        insufficient = sum("INSUFFICIENT_STOCK" in r["body"] for r in replies)
        self.assertEqual(succeeded, 1, "Exactly 1 reservation must succeed")
        self.assertEqual(insufficient, 7, "Exactly 7 reservations must fail with INSUFFICIENT_STOCK")


if __name__ == "__main__":
    unittest.main()
