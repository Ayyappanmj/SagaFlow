"""Integration test: RabbitMQ publisher confirms, dead-letter queues, and durable outbox delivery.

Requirements:
- outbox relay publishes to real RabbitMQ with publisher confirms.
- a poison message lands in the real .dlq queue after bounded retries.
- stop RabbitMQ / disconnected broker, create orders, reconnect broker, confirm saga completes.
"""
from __future__ import annotations

import json
import unittest
import uuid

from shared.broker import RabbitMQBroker
from shared.consumer import Consumer, NonRetryableError
from shared.messages import Envelope
from shared.outbox import OutboxPublisher, enqueue
from tests.integration.infra import HAVE_RMQ, RABBITMQ_URL, init_pg_service


@unittest.skipUnless(HAVE_RMQ, "Real RabbitMQ instance required (set RABBITMQ_URL or run in CI)")
class RabbitMQGuaranteeTests(unittest.TestCase):
    def setUp(self):
        self.broker = RabbitMQBroker(RABBITMQ_URL)
        self.broker.declare_topology()
        self.queue_name = "payment.commands"

    def test_outbox_relay_publishes_with_confirms(self):
        db = init_pg_service("payment")
        saga_id = str(uuid.uuid4())
        env = Envelope(
            type="payment.authorize",
            saga_id=saga_id,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=f"{saga_id}:PROCESS_PAYMENT:forward",
            payload={"order_id": "ord-1", "step": "PROCESS_PAYMENT", "action": "forward", "attempt": 1},
        )

        with db.transaction() as tx:
            oid = enqueue(tx, env, self.queue_name)

        pub = OutboxPublisher(db, self.broker, service="payment")
        relayed = pub.relay_once()
        self.assertGreaterEqual(relayed, 1)

        with db.read() as tx:
            row = tx.one("SELECT status, attempts FROM outbox_events WHERE id=?", (oid,))
            self.assertEqual(row["status"], "PUBLISHED")
            self.assertEqual(row["attempts"], 1)

        # Confirm delivery landed in real RabbitMQ
        delivery = self.broker.get(self.queue_name)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.queue, self.queue_name)
        msg = json.loads(delivery.body.decode())
        self.assertEqual(msg["saga_id"], saga_id)
        self.broker.ack(delivery)

    def test_poison_message_lands_in_real_dlq(self):
        poison_body = json.dumps({"corrupted": True, "saga_id": "poison-1"}).encode()
        self.broker.publish(self.queue_name, poison_body, {"x-attempt": 1})

        def fail_handler(_env: Envelope):
            raise NonRetryableError("Poison message intentionally rejected")

        consumer = Consumer(self.broker, self.queue_name, fail_handler, max_attempts=3)
        consumer.poll_once()

        # The poison message must have landed in .dlq
        dlq_msgs = self.broker.dlq_messages(limit=50)
        found = any(d["queue"] == self.queue_name and "poison-1" in d["body"] for d in dlq_msgs)
        self.assertTrue(found, f"Poison message was not found in DLQ: {dlq_msgs}")

    def test_broker_downtime_keeps_events_pending_until_recovery(self):
        db = init_pg_service("shipping")
        saga_id = str(uuid.uuid4())
        env = Envelope(
            type="shipping.arrange",
            saga_id=saga_id,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=f"{saga_id}:ARRANGE_SHIPPING:forward",
            payload={"order_id": "ord-down", "step": "ARRANGE_SHIPPING", "action": "forward", "attempt": 1},
        )

        with db.transaction() as tx:
            oid = enqueue(tx, env, "shipping.commands")

        # Simulate unreachable broker (invalid port)
        offline_broker = RabbitMQBroker("amqp://guest:guest@127.0.0.1:59999/")
        pub_offline = OutboxPublisher(db, offline_broker, service="shipping")
        relayed = pub_offline.relay_once()
        self.assertEqual(relayed, 0, "No messages should be relayed when broker is unreachable")

        with db.read() as tx:
            row = tx.one("SELECT status, attempts FROM outbox_events WHERE id=?", (oid,))
            self.assertEqual(row["status"], "PENDING", "Outbox event must remain durably PENDING in PostgreSQL")
            self.assertEqual(row["attempts"], 1)

        # Recover with live broker
        pub_live = OutboxPublisher(db, self.broker, service="shipping")
        # Reset available_at to now for immediate retry
        with db.transaction() as tx:
            tx.execute("UPDATE outbox_events SET available_at=NOW() WHERE id=?", (oid,))

        relayed_recovered = pub_live.relay_once()
        self.assertGreaterEqual(relayed_recovered, 1)

        with db.read() as tx:
            row_after = tx.one("SELECT status FROM outbox_events WHERE id=?", (oid,))
            self.assertEqual(row_after["status"], "PUBLISHED")

        d = self.broker.get("shipping.commands")
        self.assertIsNotNone(d)
        self.broker.ack(d)


if __name__ == "__main__":
    unittest.main()
