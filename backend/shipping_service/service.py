"""Shipping service (simulated). Cancellation is only permitted while the shipment is CREATED."""
from __future__ import annotations

import hashlib
import uuid

from shared.service_base import CommandService, Outcome, fail, ok


class ShippingService(CommandService):
    name = "shipping"

    def _handlers(self):
        return {"shipping.create": self.create, "shipping.cancel": self.cancel}

    def create(self, tx, env) -> Outcome:
        sim, now = env.payload.get("simulate") or {}, self.clock.now_iso()
        if tx.one("SELECT id FROM shipments WHERE saga_id=?", (env.saga_id,)):
            return ok(created=False, replay=True)
        if sim.get("shipping_fail"):
            return fail("NO_CARRIER_AVAILABLE", "no carrier available for this shipment")
        tracking = "TRK" + hashlib.sha1(env.saga_id.encode()).hexdigest()[:10].upper()  # deterministic
        tx.execute("INSERT INTO shipments(id, saga_id, order_id, status, tracking_number, created_at, updated_at)"
                   " VALUES (?,?,?,'CREATED',?,?,?)",
                   (str(uuid.uuid4()), env.saga_id, env.payload["order_id"], tracking, now, now))
        return ok(created=True, tracking_number=tracking)

    def cancel(self, tx, env) -> Outcome:
        if "shipping_cancel" in ((env.payload.get("simulate") or {}).get("compensation_fail") or []):
            return fail("CANCEL_REJECTED", "injected compensation failure")
        s = tx.one("SELECT id, status FROM shipments WHERE saga_id=?", (env.saga_id,))
        if s is None or s["status"] == "CANCELLED":
            return ok(created=False, noop=True)
        if s["status"] == "SHIPPED":
            return fail("CANNOT_CANCEL_SHIPPED", "shipment already left the warehouse")
        tx.execute("UPDATE shipments SET status='CANCELLED', updated_at=? WHERE id=?", (self.clock.now_iso(), s["id"]))
        return ok(created=True)

    def list_shipments(self, limit: int = 100) -> list[dict]:
        with self.db.read() as tx:
            return tx.all("SELECT * FROM shipments ORDER BY created_at DESC LIMIT ?", (limit,))
