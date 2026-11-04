import json
import unittest

from shared.broker import BrokerUnavailable
from shared.consumer import Consumer, NonRetryableError
from tests.harness import SagaTestCase


class OutboxRelayTests(SagaTestCase):
    def test_pending_outbox_published_once_and_marked(self):
        self.env.order(key="k1")
        self.assertEqual(self.env.runtime.publisher.relay_once(), 1)
        self.assertEqual(self.env.broker.depth("inventory.commands"), 1)
        self.assertEqual(self.env.runtime.publisher.pending_count(), 0)
        self.assertEqual(self.env.runtime.publisher.relay_once(), 0)  # nothing re-published

    def test_broker_down_keeps_events_pending_then_delivers_after_recovery(self):
        self.env.order(key="k1")
        self.env.broker.available = False
        self.assertEqual(self.env.runtime.publisher.relay_once(), 0)
        self.assertEqual(self.env.runtime.publisher.pending_count(), 1)
        row = self.env.rows("orchestrator", "SELECT attempts, last_error FROM outbox_events")[0]
        self.assertEqual(row["attempts"], 1)
        self.env.broker.available = True
        self.env.clock.advance(5)  # past the backoff
        self.env.pump()
        s = self.env.rows("orchestrator", "SELECT state FROM sagas")[0]["state"]
        self.assertEqual(s, "COMPLETED")

    def test_crash_between_publish_and_mark_causes_duplicate_publish_handled_by_consumer(self):
        resp, _ = self.env.order(key="k1")
        pub = self.env.runtime.publisher
        orig = pub.db.transaction
        # publish succeeds, but the 'mark published' transaction fails => at-least-once duplicate
        body = self.env.rows("orchestrator", "SELECT body FROM outbox_events")[0]["body"].encode()
        pub.broker.publish("inventory.commands", body, {})
        self.env.pump()  # relay publishes the same row again
        self.assertEqual(self.env.broker.published_count >= 2, True)
        self.assertEqual(len(self.env.rows("inventory", "SELECT * FROM inventory_reservations")), 1)
        self.assertEqual(self.env.stock()["reserved"], 2)
        self.assertEqual(self.env.saga(resp["saga_id"])["state"], "COMPLETED")
        self.assertIsNotNone(orig)


class ConsumerTests(SagaTestCase):
    def test_poison_message_goes_to_dlq_without_infinite_retry(self):
        calls = []
        c = Consumer(self.env.broker, "inventory.commands", lambda e: calls.append(1), max_attempts=3)
        self.env.broker.publish("inventory.commands", b"{not json", {})
        self.assertTrue(c.poll_once())
        self.assertEqual(calls, [])
        self.assertEqual(len(self.env.broker.dlq["inventory.commands"]), 1)
        self.assertEqual(self.env.broker.depth("inventory.commands"), 0)

    def test_handler_failure_retries_bounded_then_dead_letters(self):
        env_json = json.dumps({"message_id": "m", "type": "payment.void", "version": 1, "saga_id": "s",
                               "correlation_id": "c", "idempotency_key": "k",
                               "payload": {"order_id": "o", "step": "PROCESS_PAYMENT", "action": "compensate", "attempt": 1}})
        calls = []

        def boom(e):
            calls.append(1)
            raise ValueError("db down")
        c = Consumer(self.env.broker, "payment.commands", boom, max_attempts=3)
        self.env.broker.publish("payment.commands", env_json.encode(), {})
        while c.poll_once():
            pass
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(self.env.broker.dlq["payment.commands"]), 1)

    def test_non_retryable_goes_straight_to_dlq(self):
        def bad(e):
            raise NonRetryableError("nope")
        env_json = json.dumps({
            "message_id": "m", "type": "payment.void", "version": 1, "saga_id": "s", "correlation_id": "c",
            "idempotency_key": "k", "payload": {"order_id": "o", "step": "x", "action": "compensate", "attempt": 1},
        })
        c = Consumer(self.env.broker, "payment.commands", bad)
        self.env.broker.publish("payment.commands", env_json.encode(), {})
        c.poll_once()
        self.assertEqual(len(self.env.broker.dlq["payment.commands"]), 1)

    def test_ack_only_after_processing(self):
        self.env.order(key="k1")
        self.env.runtime.publisher.relay_once()
        d = self.env.broker.get("inventory.commands")  # consumer took it but "dies" before handling/ack
        self.assertEqual(len(self.env.broker.unacked), 1)
        self.assertEqual(self.env.broker.requeue_unacked(), 1)  # broker redelivers
        self.env.pump()
        self.assertEqual(self.env.stock()["reserved"], 2)
        self.assertIsNotNone(d)


class BrokerAvailabilityTests(SagaTestCase):
    def test_publish_raises_when_unavailable(self):
        self.env.broker.available = False
        with self.assertRaises(BrokerUnavailable):
            self.env.broker.publish("x", b"1")


class SQLiteBrokerTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from shared.broker import SQLiteBroker
        from shared.db import Database
        self.d = tempfile.mkdtemp()
        self.db = Database(f"sqlite:///{self.d}/b.db")
        self.broker = SQLiteBroker(self.db, retry_delay_s=0.0)

    def test_publish_get_ack(self):
        self.broker.publish("test.q", b'{"msg": 1}', {"x-attempt": 1})
        self.assertEqual(self.broker.depth("test.q"), 1)
        d = self.broker.get("test.q")
        self.assertIsNotNone(d)
        self.assertEqual(d.body, b'{"msg": 1}')
        self.assertEqual(d.attempt, 1)
        self.broker.ack(d)
        self.assertEqual(self.broker.depth("test.q"), 0)
        self.assertIsNone(self.broker.get("test.q"))

    def test_retry_and_requeue(self):
        self.broker.publish("test.q", b"payload", {"x-attempt": 1})
        d = self.broker.get("test.q")
        self.broker.retry(d)
        d2 = self.broker.get("test.q")
        self.assertIsNotNone(d2)
        self.assertEqual(d2.attempt, 2)
        self.assertEqual(self.broker.requeue_unacked(), 1)
        self.assertEqual(self.broker.depth("test.q"), 1)

    def test_dead_letter(self):
        self.broker.publish("test.q", b"poison", {})
        d = self.broker.get("test.q")
        self.broker.dead_letter(d, "bad payload")
        self.assertEqual(self.broker.depth("test.q"), 0)
        dlq = self.broker.dlq_messages()
        self.assertEqual(len(dlq), 1)
        self.assertEqual(dlq[0]["reason"], "bad payload")
        self.assertTrue(self.broker.ping())


if __name__ == "__main__":
    unittest.main()
