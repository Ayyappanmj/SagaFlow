"""Inventory service: owns stock and reservations. Overselling is prevented by a conditional UPDATE
(`WHERE available >= qty`) -- the row lock + predicate re-check makes concurrent reservations safe,
and the CHECK (available >= 0) constraint is a second line of defence."""
from __future__ import annotations

import uuid

from shared.service_base import CommandService, Outcome, fail, ok


class InventoryService(CommandService):
    name = "inventory"

    def _handlers(self):
        return {"inventory.reserve": self.reserve, "inventory.release": self.release}

    def seed(self, stock: dict[str, int]) -> None:
        with self.db.transaction() as tx:
            for sku, qty in stock.items():
                tx.execute("INSERT INTO inventory(sku, available, reserved, updated_at) VALUES (?,?,0,?)"
                           " ON CONFLICT(sku) DO UPDATE SET available=excluded.available, updated_at=excluded.updated_at",
                           (sku, qty, self.clock.now_iso()))

    def reserve(self, tx, env) -> Outcome:
        p, saga_id, now = env.payload, env.saga_id, self.clock.now_iso()
        if (env.payload.get("simulate") or {}).get("inventory_reject"):
            return fail("INVENTORY_REJECTED", "inventory service rejected the request")
        if tx.one("SELECT id FROM inventory_reservations WHERE saga_id=?", (saga_id,)):
            return ok(created=False, replay=True)  # idempotent replay
        rid = str(uuid.uuid4())
        items = sorted(p["items"], key=lambda i: i["sku"])  # stable lock order avoids deadlocks
        try:
            with tx.savepoint():  # all-or-nothing for the order's lines
                tx.execute("INSERT INTO inventory_reservations(id, saga_id, order_id, status, created_at, updated_at)"
                           " VALUES (?,?,?,'RESERVED',?,?)", (rid, saga_id, p["order_id"], now, now))
                for it in items:
                    n = tx.execute("UPDATE inventory SET available=available-?, reserved=reserved+?, updated_at=?"
                                   " WHERE sku=? AND available>=?",
                                   (it["quantity"], it["quantity"], now, it["sku"], it["quantity"]))
                    if n == 0:
                        raise _Insufficient(it["sku"])
                    tx.execute("INSERT INTO reservation_items(reservation_id, sku, quantity) VALUES (?,?,?)",
                               (rid, it["sku"], it["quantity"]))
        except _Insufficient as e:
            return fail("INSUFFICIENT_STOCK", f"insufficient stock for sku {e.args[0]}")
        return ok(created=True, reservation_id=rid)

    def release(self, tx, env) -> Outcome:
        if "inventory_release" in ((env.payload.get("simulate") or {}).get("compensation_fail") or []):
            return fail("RELEASE_REJECTED", "injected compensation failure")
        now = self.clock.now_iso()
        r = tx.one("SELECT id, status FROM inventory_reservations WHERE saga_id=?", (env.saga_id,))
        if r is None or r["status"] == "RELEASED":
            return ok(created=False, noop=True)  # nothing reserved / already released
        for it in tx.all("SELECT sku, quantity FROM reservation_items WHERE reservation_id=?", (r["id"],)):
            tx.execute("UPDATE inventory SET available=available+?, reserved=reserved-?, updated_at=? WHERE sku=?",
                       (it["quantity"], it["quantity"], now, it["sku"]))
        tx.execute("UPDATE inventory_reservations SET status='RELEASED', updated_at=? WHERE id=?", (now, r["id"]))
        return ok(created=True)

    # read models for the dashboard
    def list_stock(self) -> list[dict]:
        with self.db.read() as tx:
            return tx.all("SELECT sku, available, reserved, updated_at FROM inventory ORDER BY sku")

    def list_reservations(self, limit: int = 100) -> list[dict]:
        with self.db.read() as tx:
            return tx.all("SELECT * FROM inventory_reservations ORDER BY created_at DESC LIMIT ?", (limit,))


class _Insufficient(Exception):
    pass
