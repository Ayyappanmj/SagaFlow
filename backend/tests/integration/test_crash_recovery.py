"""Integration test: Orchestrator crash recovery mid-saga without duplicate effects.

Requirement: Kill the orchestrator mid-saga, restart it, and confirm the saga completes
with no duplicate payment or reservation.
"""
from __future__ import annotations

import unittest
import uuid

from inventory_service.service import InventoryService
from orchestrator.engine import SagaEngine
from orchestrator.orders import create_order
from orchestrator.runtime import OrchestratorRuntime
from payment_service.service import PaymentService
from shared.broker import RabbitMQBroker
from shared.consumer import Consumer
from shared.outbox import OutboxPublisher
from shared.retry import RetryPolicy
from shipping_service.service import ShippingService
from tests.integration.infra import HAVE_INFRA, RABBITMQ_URL, init_pg_service


@unittest.skipUnless(HAVE_INFRA, "Real PostgreSQL and RabbitMQ required (run in CI or with full stack)")
class CrashRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.broker = RabbitMQBroker(RABBITMQ_URL)
        self.broker.declare_topology()

        self.db_orch = init_pg_service("orchestrator")
        self.db_inv = init_pg_service("inventory")
        self.db_pay = init_pg_service("payment")
        self.db_shp = init_pg_service("shipping")

        self.inv_svc = InventoryService(self.db_inv)
        self.pay_svc = PaymentService(self.db_pay)
        self.shp_svc = ShippingService(self.db_shp)

        self.sku = f"CRASH_SKU_{uuid.uuid4().hex[:8]}"
        self.inv_svc.seed({self.sku: 10})

    def test_kill_orchestrator_mid_saga_and_recover_without_duplicates(self):
        policy = RetryPolicy(max_attempts=3, base_delay_s=0.5)
        engine = SagaEngine(self.db_orch, policy)
        runtime = OrchestratorRuntime(engine, self.broker, stale_after_s=0.0)

        # 1. Place order
        key = f"crash-order-{uuid.uuid4()}"
        resp, _ = create_order(
            self.db_orch,
            engine,
            {"customer_ref": "crash-test", "items": [{"sku": self.sku, "quantity": 2, "unit_price_cents": 500}]},
            key,
            str(uuid.uuid4()),
        )
        saga_id = resp["saga_id"]

        # 2. Outbox relay sends step 1 (RESERVE_INVENTORY) to RabbitMQ
        runtime.publisher.relay_once()

        # 3. Inventory consumer processes it and enqueues reply
        inv_consumer = Consumer(self.broker, "inventory.commands", self.inv_svc.handle)
        inv_consumer.poll_once()
        OutboxPublisher(self.db_inv, self.broker, service="inventory").relay_once()

        # 4. Orchestrator consumes reply and advances to PROCESS_PAYMENT
        runtime.consumer.poll_once()
        runtime.publisher.relay_once()

        # --- SIMULATE CRASH: Orchestrator is killed mid-saga ---
        # The runtime instance is terminated/dropped without clean shutdown
        del runtime
        del engine

        # While orchestrator was "dead", payment service processes the command and enqueues reply
        pay_consumer = Consumer(self.broker, "payment.commands", self.pay_svc.handle)
        pay_consumer.poll_once()
        OutboxPublisher(self.db_pay, self.broker, service="payment").relay_once()

        # --- RESTART: Orchestrator process restarts from fresh instance on SAME DB and MQ ---
        engine_restarted = SagaEngine(self.db_orch, policy)
        runtime_restarted = OrchestratorRuntime(engine_restarted, self.broker, stale_after_s=0.0)
        runtime_restarted.startup_recovery()

        # Orchestrator picks up the pending payment reply and dispatches shipping
        runtime_restarted.consumer.poll_once()
        runtime_restarted.publisher.relay_once()

        # Shipping processes command and replies
        shp_consumer = Consumer(self.broker, "shipping.commands", self.shp_svc.handle)
        shp_consumer.poll_once()
        OutboxPublisher(self.db_shp, self.broker, service="shipping").relay_once()

        # Orchestrator consumes final reply
        runtime_restarted.consumer.poll_once()

        # Verify saga reached COMPLETED
        with self.db_orch.read() as tx:
            saga = tx.one("SELECT state FROM sagas WHERE id=?", (saga_id,))
            self.assertEqual(saga["state"], "COMPLETED")

        # Verify EXACTLY ONE reservation and EXACTLY ONE payment (no duplicate effects)
        with self.db_inv.read() as tx:
            stock = tx.one("SELECT available, reserved FROM inventory WHERE sku=?", (self.sku,))
            res_count = tx.one(
                "SELECT COUNT(*) AS n FROM inventory_reservations WHERE saga_id=?", (saga_id,)
            )["n"]
            self.assertEqual(stock["available"], 8)
            self.assertEqual(stock["reserved"], 2)
            self.assertEqual(res_count, 1, "Must have exactly 1 reservation record")

        with self.db_pay.read() as tx:
            pay_count = tx.one("SELECT COUNT(*) AS n FROM payments WHERE saga_id=?", (saga_id,))["n"]
            self.assertEqual(pay_count, 1, "Must have exactly 1 payment record")


if __name__ == "__main__":
    unittest.main()
