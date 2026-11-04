"""Base class for business services (inventory / payment / shipping).

handle() runs in ONE local transaction: dedupe check -> business effect -> processed_messages -> reply outbox.
Duplicate deliveries re-emit the stored reply instead of repeating the effect.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from .consumer import NonRetryableError
from .db import Database, Tx
from .messages import REPLY_TYPE, Envelope
from .metrics import METRICS
from .outbox import enqueue
from .timeutil import Clock


@dataclass
class Outcome:
    status: str  # SUCCEEDED | FAILED
    retryable: bool = False
    error_code: str | None = None
    error_detail: str | None = None
    created: bool = False  # True when this call produced the business effect (vs. idempotent replay)
    data: dict = field(default_factory=dict)


def ok(created: bool = False, **data) -> Outcome:
    return Outcome("SUCCEEDED", created=created, data=data)


def fail(code: str, detail: str = "", retryable: bool = False) -> Outcome:
    return Outcome("FAILED", retryable=retryable, error_code=code, error_detail=detail)


class CommandService:
    name = "service"
    handlers: dict = {}

    def __init__(self, db: Database, clock: Clock | None = None):
        self.db, self.clock = db, clock or Clock()
        self.handlers = self._handlers()

    def _handlers(self) -> dict:
        raise NotImplementedError

    def handle(self, env: Envelope) -> None:
        fn = self.handlers.get(env.type)
        if fn is None:
            raise NonRetryableError(f"{self.name} cannot handle {env.type}")
        sim = env.payload.get("simulate") or {}
        if sim.get("delay_ms"):
            time.sleep(min(int(sim["delay_ms"]), 5000) / 1000)
        with self.db.transaction() as tx:
            prev = tx.one("SELECT result_json FROM processed_messages WHERE message_id=? AND consumer=?",
                          (env.message_id, self.name))
            if prev is not None:
                METRICS.inc("sagaflow_duplicate_messages_total", "Duplicate deliveries ignored", service=self.name)
                self._reply(tx, env, json.loads(prev["result_json"]))  # re-emit the same answer
                return
            out: Outcome = fn(tx, env)
            reply = {"status": out.status, "retryable": out.retryable, "error_code": out.error_code,
                     "error_detail": out.error_detail, "data": out.data}
            tx.execute("INSERT INTO processed_messages(message_id, consumer, result_json, processed_at)"
                       " VALUES (?,?,?,?)", (env.message_id, self.name, json.dumps(reply), self.clock.now_iso()))
            if out.created and self.name in (sim.get("drop_reply_once") or []):
                return  # fault injection: effect committed, reply lost (like a crash before publishing)
            self._reply(tx, env, reply)

    def _reply(self, tx: Tx, env: Envelope, reply: dict) -> None:
        p = env.payload
        msg = Envelope(
            type=REPLY_TYPE, saga_id=env.saga_id, correlation_id=env.correlation_id,
            idempotency_key=env.idempotency_key,
            message_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "reply:" + env.message_id)),  # deterministic
            payload={"service": self.name, "step": p["step"], "action": p["action"], "attempt": p["attempt"],
                     "order_id": p["order_id"], **reply})
        enqueue(tx, msg, "orchestrator.replies", self.clock)
