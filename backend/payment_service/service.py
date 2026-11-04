"""Payment service (simulated). Deterministic outcomes: decline if amount > limit or injected.
authorize and void are idempotent; a void never reverses a payment that did not happen."""
from __future__ import annotations

import uuid

from shared.service_base import CommandService, Outcome, fail, ok


class PaymentService(CommandService):
    name = "payment"

    def __init__(self, db, clock=None, limit_cents: int = 100_000):
        self.limit_cents = limit_cents
        super().__init__(db, clock)

    def _handlers(self):
        return {"payment.authorize": self.authorize, "payment.void": self.void}

    def _op(self, tx, pid, op, key, now):
        tx.execute("INSERT INTO payment_operations(id, payment_id, op_type, idempotency_key, created_at)"
                   " VALUES (?,?,?,?,?)", (str(uuid.uuid4()), pid, op, key, now))

    def authorize(self, tx, env) -> Outcome:
        p, sim, now = env.payload, env.payload.get("simulate") or {}, self.clock.now_iso()
        existing = tx.one("SELECT id, status FROM payments WHERE saga_id=?", (env.saga_id,))
        if existing:
            if existing["status"] == "DECLINED":
                return fail("PAYMENT_DECLINED", "payment was declined")
            return ok(created=False, replay=True)
        if int(sim.get("payment_timeout", 0)) >= int(p["attempt"]):
            return fail("TIMEOUT", "payment provider timed out", retryable=True)  # no effect was produced
        pid = str(uuid.uuid4())
        amount = int(p.get("amount_cents", 0))
        declined = bool(sim.get("payment_decline")) or amount > self.limit_cents
        tx.execute("INSERT INTO payments(id, saga_id, order_id, amount_cents, status, created_at, updated_at)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (pid, env.saga_id, p["order_id"], amount, "DECLINED" if declined else "AUTHORIZED", now, now))
        self._op(tx, pid, "DECLINE" if declined else "AUTHORIZE", env.idempotency_key, now)
        if declined:
            return fail("PAYMENT_DECLINED", "payment was declined")
        return ok(created=True, payment_id=pid)

    def void(self, tx, env) -> Outcome:
        if "payment_void" in ((env.payload.get("simulate") or {}).get("compensation_fail") or []):
            return fail("VOID_REJECTED", "injected compensation failure")
        now = self.clock.now_iso()
        pay = tx.one("SELECT id, status FROM payments WHERE saga_id=?", (env.saga_id,))
        if pay is None or pay["status"] != "AUTHORIZED":
            return ok(created=False, noop=True)  # never reverse a payment that did not occur
        tx.execute("UPDATE payments SET status='VOIDED', updated_at=? WHERE id=?", (now, pay["id"]))
        self._op(tx, pay["id"], "VOID", env.idempotency_key, now)
        return ok(created=True)

    def list_payments(self, limit: int = 100) -> list[dict]:
        with self.db.read() as tx:
            return tx.all("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,))
