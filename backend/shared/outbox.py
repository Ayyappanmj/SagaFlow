"""Transactional outbox: enqueue() runs inside the caller's DB transaction; the relay publishes later.

Publishing and marking-as-published are NOT atomic, so a crash in between re-publishes the event
(at-least-once). Consumers therefore must be idempotent (see processed_messages).
"""
from __future__ import annotations

import logging
import uuid

from .broker import BrokerUnavailable
from .db import Database, Tx
from .messages import Envelope
from .metrics import METRICS
from .retry import RetryPolicy
from .timeutil import Clock, add_seconds, iso

logger = logging.getLogger("outbox")


def enqueue(tx: Tx, env: Envelope, destination: str, clock: Clock | None = None,
            delay_s: float = 0.0, copies: int = 1) -> str:
    clock = clock or Clock()
    now = clock.now()
    env.occurred_at = iso(now)
    oid = str(uuid.uuid4())
    tx.execute(
        "INSERT INTO outbox_events (id, destination, message_type, saga_id, correlation_id, body, status,"
        " attempts, publish_copies, available_at, created_at) VALUES (?,?,?,?,?,?,'PENDING',0,?,?,?)",
        (oid, destination, env.type, env.saga_id, env.correlation_id, env.to_json(), copies,
         iso(add_seconds(now, delay_s)), iso(now)))
    return oid


class OutboxPublisher:
    def __init__(self, db: Database, broker, clock: Clock | None = None,
                 policy: RetryPolicy | None = None, service: str = "svc"):
        self.db, self.broker, self.clock = db, broker, clock or Clock()
        self.policy = policy or RetryPolicy(base_delay_s=1.0, max_delay_s=30.0)
        self.service = service

    def pending_count(self) -> int:
        with self.db.read() as tx:
            return tx.one("SELECT COUNT(*) AS n FROM outbox_events WHERE status='PENDING'")["n"]

    def relay_once(self, batch: int = 50) -> int:
        """Publish due outbox rows. Returns number marked PUBLISHED."""
        now = self.clock.now()
        with self.db.read() as tx:
            rows = tx.all("SELECT * FROM outbox_events WHERE status='PENDING' AND available_at<=?"
                          " ORDER BY created_at, id LIMIT ?", (iso(now), batch))
        done = 0
        for r in rows:
            try:
                for _ in range(r["publish_copies"]):
                    self.broker.publish(r["destination"], r["body"].encode(),
                                        {"message_type": r["message_type"], "saga_id": r["saga_id"],
                                         "correlation_id": r["correlation_id"], "x-attempt": 1})
            except BrokerUnavailable as e:
                with self.db.transaction() as tx:
                    tx.execute("UPDATE outbox_events SET attempts=attempts+1, last_error=?, available_at=?"
                               " WHERE id=?",
                               (str(e)[:200], iso(add_seconds(now, self.policy.delay(r["attempts"] + 1))), r["id"]))
                METRICS.inc("sagaflow_outbox_publish_failures_total", "Outbox publish failures", service=self.service)
                break  # broker is down: stop this batch, retry next tick (preserves ordering)
            with self.db.transaction() as tx:  # crash before this line => duplicate publish later
                done += tx.execute("UPDATE outbox_events SET status='PUBLISHED', published_at=?, attempts=attempts+1"
                                   " WHERE id=? AND status='PENDING'", (iso(now), r["id"]))
        return done
