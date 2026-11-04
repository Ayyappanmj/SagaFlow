"""End-to-end saga scenarios through real SQL schemas, outbox relays, consumers and services."""
import threading
import unittest

from orchestrator.engine import NotEligible
from orchestrator.orders import IdempotencyConflict
from tests.harness import SagaTestCase


class HappyPathTests(SagaTestCase):
    def test_successful_order(self):
        r, _ = self.env.order(key="k1")
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual(s["state"], "COMPLETED")
        self.assertEqual([x["status"] for x in s["steps"]], ["COMPLETED"] * 3)
        self.assertEqual(self.env.stock(), {"available": 8, "reserved": 2})
        self.assertEqual(
            self.env.rows("payment", "SELECT status, amount_cents FROM payments"),
            [{"status": "AUTHORIZED", "amount_cents": 2000}],
        )
        self.assertEqual(self.env.rows("shipping", "SELECT status FROM shipments")[0]["status"], "CREATED")
        self.assertEqual(self.env.rows("orchestrator", "SELECT status FROM orders")[0]["status"], "COMPLETED")
        ev = self.env.events(r["saga_id"])
        self.assertEqual(ev[0:2], ["SAGA_CREATED", "SAGA_STARTED"])
        self.assertEqual(ev[-1], "SAGA_COMPLETED")


class FailureScenarioTests(SagaTestCase):
    def test_insufficient_inventory_fails_without_compensation(self):
        r, _ = self.env.order([{"sku": "WIDGET", "quantity": 99, "unit_price_cents": 1}], key="k1")
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual((s["state"], s["error_code"]), ("FAILED", "INSUFFICIENT_STOCK"))
        self.assertEqual(self.env.stock()["available"], 10)
        self.assertEqual(self.env.rows("payment", "SELECT * FROM payments"), [])

    def test_inventory_rejection_injected(self):
        r, _ = self.env.order(key="k1", simulate={"inventory_reject": True})
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "FAILED")

    def test_payment_decline_releases_inventory_and_never_voids(self):
        r, _ = self.env.order(key="k1", simulate={"payment_decline": True})
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual(s["state"], "COMPENSATED")
        self.assertEqual(self.env.stock(), {"available": 10, "reserved": 0})
        self.assertEqual(self.env.rows("payment", "SELECT status FROM payments")[0]["status"], "DECLINED")
        self.assertEqual(self.env.rows("payment", "SELECT * FROM payment_operations WHERE op_type='VOID'"), [])
        steps = {x["step_name"]: x for x in s["steps"]}
        self.assertEqual(steps["PROCESS_PAYMENT"]["compensation_status"], "NONE")
        self.assertEqual(steps["RESERVE_INVENTORY"]["compensation_status"], "COMPLETED")
        self.assertEqual(self.env.rows("orchestrator", "SELECT status FROM orders")[0]["status"], "CANCELLED")

    def test_payment_limit_declines_deterministically(self):
        r, _ = self.env.order([{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 200_000}], key="k1")
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPENSATED")

    def test_shipping_failure_compensates_in_reverse_order(self):
        r, _ = self.env.order(key="k1", simulate={"shipping_fail": True})
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual(s["state"], "COMPENSATED")
        self.assertEqual(self.env.stock(), {"available": 10, "reserved": 0})
        self.assertEqual(self.env.rows("payment", "SELECT status FROM payments")[0]["status"], "VOIDED")
        comp = [e["step_name"] for e in self._hist(r["saga_id"]) if e["event_type"] == "COMPENSATION_DISPATCHED"]
        self.assertEqual(comp, ["PROCESS_PAYMENT", "RESERVE_INVENTORY"])  # payment undone BEFORE inventory

    def _hist(self, saga_id):
        from orchestrator.queries import get_history
        return get_history(self.env.dbs["orchestrator"], saga_id)

    def test_compensation_failure_is_never_marked_compensated_and_can_be_recovered(self):
        r, _ = self.env.order(key="k1", simulate={"shipping_fail": True, "compensation_fail": ["payment_void"]})
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual(s["state"], "REQUIRES_ATTENTION")
        self.assertEqual(s["error_code"], "COMPENSATION_FAILED")
        steps = {x["step_name"]: x for x in s["steps"]}
        self.assertEqual(steps["PROCESS_PAYMENT"]["compensation_status"], "FAILED")
        self.assertEqual(steps["RESERVE_INVENTORY"]["compensation_status"], "PENDING")  # still owed
        self.assertEqual(self.env.stock()["reserved"], 2)  # inventory NOT released yet
        self.assertEqual(self.env.rows("payment", "SELECT status FROM payments")[0]["status"], "AUTHORIZED")
        # operator fixes the cause and retries: compensation resumes where it stopped
        self.env.engine.retry(r["saga_id"], clear_simulation=True)
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual(s["state"], "COMPENSATED")
        self.assertEqual(self.env.rows("payment", "SELECT status FROM payments")[0]["status"], "VOIDED")
        self.assertEqual(self.env.stock(), {"available": 10, "reserved": 0})

    def test_transient_payment_timeouts_retry_with_backoff_then_succeed(self):
        r, _ = self.env.order(key="k1", simulate={"payment_timeout": 2})
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual(s["state"], "COMPLETED")
        self.assertEqual(s["retry_count"], 2)
        self.assertEqual(len(self.env.rows("payment", "SELECT * FROM payments")), 1)  # one charge, not three
        self.assertIn("STEP_RETRY_SCHEDULED", self.env.events(r["saga_id"]))

    def test_exhausted_retries_represent_unknown_outcome_and_manual_retry_resolves(self):
        r, _ = self.env.order(key="k1", simulate={"payment_timeout": 3})
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual((s["state"], s["error_code"]), ("REQUIRES_ATTENTION", "OUTCOME_UNKNOWN"))
        self.assertEqual({x["step_name"]: x["status"] for x in s["steps"]}["PROCESS_PAYMENT"], "UNKNOWN")
        self.assertEqual(self.env.stock()["reserved"], 2)  # not compensated blindly
        self.env.engine.retry(r["saga_id"])
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")
        self.assertEqual(len(self.env.rows("payment", "SELECT * FROM payments")), 1)

    def test_retry_rejected_for_non_eligible_states(self):
        r, _ = self.env.order(key="k1")
        self.env.pump()
        with self.assertRaises(NotEligible):
            self.env.engine.retry(r["saga_id"])
        with self.assertRaises(NotEligible):
            self.env.engine.recover(r["saga_id"])


class DuplicateAndConcurrencyTests(SagaTestCase):
    stock = {"WIDGET": 5}

    def test_duplicate_order_submission_is_idempotent(self):
        items = [{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 100}]
        a, created_a = self.env.order(items, key="same")
        b, created_b = self.env.order(items, key="same")
        self.assertEqual((created_a, created_b, a), (True, False, b))
        self.env.pump()
        self.assertEqual(len(self.env.rows("orchestrator", "SELECT * FROM orders")), 1)
        self.assertEqual(self.env.stock()["reserved"], 1)
        with self.assertRaises(IdempotencyConflict):
            self.env.order([{"sku": "WIDGET", "quantity": 2, "unit_price_cents": 100}], key="same")

    def test_concurrent_identical_requests_create_one_order(self):
        items = [{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 100}]
        out = []
        ts = [threading.Thread(target=lambda: out.append(self.env.order(items, key="race"))) for _ in range(6)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len({o[0]["order_id"] for o in out}), 1)
        self.assertEqual(sum(1 for o in out if o[1]), 1)

    def test_duplicate_delivery_injection_has_single_effect(self):
        r, _ = self.env.order([{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 100}], key="k1",
                              simulate={"duplicate_delivery": True})
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")
        self.assertEqual(self.env.stock(), {"available": 4, "reserved": 1})
        self.assertEqual(len(self.env.rows("payment", "SELECT * FROM payments")), 1)
        self.assertEqual(len(self.env.rows("shipping", "SELECT * FROM shipments")), 1)

    def test_competing_orders_for_scarce_stock(self):
        item = [{"sku": "WIDGET", "quantity": 4, "unit_price_cents": 100}]
        a, _ = self.env.order(item, key="a")
        b, _ = self.env.order(item, key="b")
        self.env.pump()
        states = sorted(self.env.saga(x["saga_id"])["state"] for x in (a, b))
        self.assertEqual(states, ["COMPLETED", "FAILED"])
        self.assertEqual(self.env.stock(), {"available": 1, "reserved": 4})


class CrashRecoveryTests(SagaTestCase):
    def test_lost_reply_is_recovered_without_repeating_effects(self):
        r, _ = self.env.order(key="k1", simulate={"drop_reply_once": ["inventory"]})
        self.env.pump()
        s = self.env.saga(r["saga_id"])
        self.assertEqual((s["state"], s["current_step"]), ("RUNNING", "RESERVE_INVENTORY"))  # stuck: reply lost
        self.assertEqual(self.env.stock()["reserved"], 2)  # effect did happen
        self.assertEqual(self.env.engine.recover_stale(60), [])  # not stale yet
        self.env.clock.advance(61)
        self.assertEqual(self.env.engine.recover_stale(60), [r["saga_id"]])
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")
        self.assertEqual(self.env.stock(), {"available": 8, "reserved": 2})  # reserved ONCE
        self.assertIn("SAGA_RECOVERED_REDISPATCH", self.env.events(r["saga_id"]))

    def test_worker_killed_after_commit_before_ack_redelivery_is_deduplicated(self):
        r, _ = self.env.order(key="k1")
        self.env.runtime.publisher.relay_once()
        d = self.env.broker.get("inventory.commands")
        from shared.messages import Envelope
        self.env.inventory.handle(Envelope.from_json(d.body))  # committed ...
        # ... worker dies before ack
        self.assertEqual(self.env.broker.requeue_unacked(), 1)
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")
        self.assertEqual(self.env.stock(), {"available": 8, "reserved": 2})

    def test_restart_with_unpublished_outbox_loses_nothing(self):
        r, _ = self.env.order(key="k1")  # process "dies" before the relay ever ran
        self.env.restart()  # new objects, same databases
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")

    def test_restart_mid_saga_resumes_via_startup_recovery(self):
        r, _ = self.env.order(key="k1")
        self.env.runtime.publisher.relay_once()
        self.env.broker.queues.clear()  # simulate a broker that lost its (non-persistent) state
        self.env.restart()
        self.env.clock.advance(120)
        self.assertEqual(self.env.runtime.startup_recovery(), [r["saga_id"]])
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")
        self.assertEqual(self.env.stock(), {"available": 8, "reserved": 2})

    def test_manual_recover_endpoint_logic(self):
        r, _ = self.env.order(key="k1")
        self.env.runtime.publisher.relay_once()
        self.env.broker.queues.clear()
        self.assertTrue(self.env.engine.recover(r["saga_id"]))
        self.env.pump()
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")

    def test_recover_skips_when_command_still_in_outbox(self):
        r, _ = self.env.order(key="k1")
        self.assertFalse(self.env.engine.recover(r["saga_id"]))

    def test_late_duplicate_reply_ignored(self):
        r, _ = self.env.order(key="k1")
        self.env.pump()
        before = self.env.events(r["saga_id"])
        import json

        from shared.messages import Envelope
        late = Envelope(type="saga.reply", saga_id=r["saga_id"], correlation_id="c", idempotency_key="k",
                        payload={"service": "payment", "step": "PROCESS_PAYMENT", "action": "forward", "status": "FAILED",
                                 "attempt": 1, "retryable": False, "error_code": "X", "order_id": "o"})
        self.env.engine.handle_reply(late)
        self.assertEqual(self.env.saga(r["saga_id"])["state"], "COMPLETED")  # untouched
        self.assertEqual(self.env.events(r["saga_id"])[:len(before)], before)
        self.assertIsNotNone(json)


if __name__ == "__main__":
    unittest.main()
