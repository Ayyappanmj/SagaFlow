import threading
import unittest

from orchestrator.state_machine import ConcurrentModification
from shared.db import IntegrityError
from shared.messages import Envelope
from shared.outbox import enqueue
from tests.harness import Env, SagaTestCase


def reserve_env(saga_id, sku, qty, attempt=1):
    return Envelope(type="inventory.reserve", saga_id=saga_id, correlation_id="c", idempotency_key=saga_id,
                    payload={"order_id": "o-" + saga_id, "step": "RESERVE_INVENTORY", "action": "forward",
                             "attempt": attempt, "items": [{"sku": sku, "quantity": qty}], "simulate": {}})


class ConcurrentInventoryTests(unittest.TestCase):
    def test_no_overselling_under_concurrency(self):
        env = Env({"WIDGET": 5})
        self.addCleanup(env.cleanup)
        errors = []

        def worker(i):
            try:
                env.inventory.handle(reserve_env(f"saga-{i}", "WIDGET", 4))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        stock = env.stock()
        self.assertEqual((stock["available"], stock["reserved"]), (1, 4))  # exactly ONE reservation of 4
        self.assertEqual(len(env.rows("inventory", "SELECT * FROM inventory_reservations")), 1)
        replies = env.rows("inventory", "SELECT body FROM outbox_events")
        self.assertEqual(len(replies), 8)
        self.assertEqual(sum('"status":"SUCCEEDED"' in r["body"] for r in replies), 1)
        self.assertEqual(sum("INSUFFICIENT_STOCK" in r["body"] for r in replies), 7)

    def test_partial_multi_item_reservation_rolls_back(self):
        env = Env({"A": 5, "B": 1})
        self.addCleanup(env.cleanup)
        e = reserve_env("s1", "A", 3)
        e.payload["items"].append({"sku": "B", "quantity": 2})
        env.inventory.handle(e)
        self.assertEqual(env.stock("A")["available"], 5)  # A's decrement rolled back with the savepoint
        self.assertEqual(env.rows("inventory", "SELECT * FROM inventory_reservations"), [])


class TransactionTests(SagaTestCase):
    def test_outbox_row_rolls_back_with_state_change(self):
        env = self.env
        with self.assertRaises(RuntimeError):
            with env.dbs["orchestrator"].transaction() as tx:
                env.engine.create_saga  # noqa: B018
                tx.execute("INSERT INTO orders(id, customer_ref, status, total_cents, idempotency_key, created_at, updated_at)"
                           " VALUES ('o1','c','PENDING',0,'k1','t','t')")
                enqueue(tx, reserve_env("s1", "WIDGET", 1), "inventory.commands", env.clock)
                raise RuntimeError("boom")
        self.assertEqual(env.rows("orchestrator", "SELECT * FROM orders"), [])
        self.assertEqual(env.rows("orchestrator", "SELECT * FROM outbox_events"), [])

    def test_order_creation_writes_state_and_outbox_atomically(self):
        resp, created = self.env.order(key="k-atomic")
        self.assertTrue(created)
        ob = self.env.rows("orchestrator", "SELECT destination, status FROM outbox_events")
        self.assertEqual([(r["destination"], r["status"]) for r in ob], [("inventory.commands", "PENDING")])

    def test_unique_constraints(self):
        self.env.order(key="k-1")
        with self.assertRaises(IntegrityError):
            with self.env.dbs["orchestrator"].transaction() as tx:
                tx.execute(
                    "INSERT INTO idempotency_records(key, request_hash, response_json, created_at)"
                    " VALUES ('k-1','h','{}','t')"
                )
        with self.assertRaises(IntegrityError):  # inventory can never go negative
            with self.env.dbs["inventory"].transaction() as tx:
                tx.execute("UPDATE inventory SET available=-1 WHERE sku='WIDGET'")

    def test_optimistic_concurrency_rejects_stale_writer(self):
        resp, _ = self.env.order(key="k-oc")
        e = self.env.engine
        with self.env.dbs["orchestrator"].transaction() as tx:
            stale = e._load(tx, resp["saga_id"])
        with self.env.dbs["orchestrator"].transaction() as tx:
            fresh = e._load(tx, resp["saga_id"])
            e._save(tx, fresh, retry_count=5)
        with self.assertRaises(ConcurrentModification):
            with self.env.dbs["orchestrator"].transaction() as tx:
                e._save(tx, stale, retry_count=9)
        self.assertEqual(self.env.saga(resp["saga_id"])["retry_count"], 5)


if __name__ == "__main__":
    unittest.main()
