"""Saga orchestration engine. Every handler runs in ONE local transaction that updates saga state,
appends history, and enqueues the next command in the outbox -- so state and intent can't diverge."""
from __future__ import annotations

import json
import logging
import uuid

from shared.db import Database, Tx
from shared.messages import Envelope
from shared.metrics import METRICS
from shared.outbox import enqueue
from shared.retry import RetryPolicy
from shared.timeutil import Clock, add_seconds, iso

from .state_machine import IN_FLIGHT, TERMINAL, ConcurrentModification, SagaState, order_status_for, validate_transition
from .workflow import BY_NAME, STEPS, compensation_plan

logger = logging.getLogger("orchestrator")
S = SagaState


class NotEligible(Exception):
    """Operator action not allowed in the saga's current state (-> HTTP 409)."""


class SagaNotFound(Exception):
    pass


class SagaEngine:
    CONSUMER = "orchestrator"

    def __init__(self, db: Database, policy: RetryPolicy | None = None, clock: Clock | None = None):
        self.db, self.policy, self.clock = db, policy or RetryPolicy(), clock or Clock()

    # ------------------------------------------------------------------ helpers
    def _now(self) -> str:
        return self.clock.now_iso()

    def _load(self, tx: Tx, saga_id: str) -> dict:
        s = tx.one("SELECT * FROM sagas WHERE id=?", (saga_id,))
        if s is None:
            raise SagaNotFound(saga_id)
        return s

    def _steps(self, tx: Tx, saga_id: str) -> dict[str, dict]:
        return {r["step_name"]: r for r in tx.all("SELECT * FROM saga_steps WHERE saga_id=? ORDER BY ordinal", (saga_id,))}

    def _event(self, tx: Tx, saga: dict, event_type: str, prev: str | None, new: str, step: str | None = None,
               attempt: int = 0, error: str | None = None, comp: str | None = None) -> None:
        seq = tx.one("SELECT COALESCE(MAX(seq),0)+1 AS n FROM saga_events WHERE saga_id=?", (saga["id"],))["n"]
        tx.execute("INSERT INTO saga_events(id, seq, saga_id, step_name, previous_state, new_state, event_type,"
                   " attempt, error_detail, compensation_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()), seq, saga["id"], step, prev, new, event_type, attempt, error, comp, self._now()))

    def _save(self, tx: Tx, saga: dict, new_state: SagaState | None = None, **fields) -> None:
        """Optimistic-concurrency update: fails if the version changed since we loaded the saga."""
        if new_state is not None:
            validate_transition(saga["state"], new_state)
            fields["state"] = new_state.value
        fields["updated_at"] = self._now()
        if new_state in TERMINAL:
            fields["completed_at"] = self._now()
        sets = ", ".join(f"{k}=?" for k in fields)
        n = tx.execute(f"UPDATE sagas SET {sets}, version=version+1 WHERE id=? AND version=?",
                       (*fields.values(), saga["id"], saga["version"]))
        if n == 0:
            raise ConcurrentModification(saga["id"])
        saga.update(fields)
        saga["version"] += 1
        if new_state is not None:
            tx.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                       (order_status_for(new_state), self._now(), saga["order_id"]))

    def _update_step(self, tx: Tx, saga_id: str, step: str, **fields) -> None:
        fields["updated_at"] = self._now()
        sets = ", ".join(f"{k}=?" for k in fields)
        tx.execute(f"UPDATE saga_steps SET {sets} WHERE saga_id=? AND step_name=?", (*fields.values(), saga_id, step))

    def _send(self, tx: Tx, saga: dict, step: str, action: str, attempt: int, delay_s: float = 0.0) -> None:
        sd = BY_NAME[step]
        order = tx.one("SELECT total_cents FROM orders WHERE id=?", (saga["order_id"],))
        items = tx.all("SELECT sku, quantity FROM order_items WHERE order_id=? ORDER BY sku", (saga["order_id"],))
        sim = json.loads(saga["simulate_json"])
        env = Envelope(type=sd.forward if action == "forward" else sd.compensate, saga_id=saga["id"],
                       correlation_id=saga["correlation_id"], idempotency_key=f"{saga['id']}:{step}:{action}",
                       payload={"order_id": saga["order_id"], "step": step, "action": action, "attempt": attempt,
                                "items": items, "amount_cents": order["total_cents"], "simulate": sim})
        copies = 2 if sim.get("duplicate_delivery") and action == "forward" else 1
        enqueue(tx, env, f"{sd.service}.commands", self.clock, delay_s, copies)

    # ------------------------------------------------------------------ start
    def create_saga(self, tx: Tx, order_id: str, correlation_id: str, idempotency_key: str, simulate: dict) -> str:
        saga_id, now = str(uuid.uuid4()), self._now()
        tx.execute("INSERT INTO sagas(id, order_id, state, current_step, correlation_id, idempotency_key,"
                   " simulate_json, created_at, updated_at) VALUES (?,?,'PENDING',NULL,?,?,?,?,?)",
                   (saga_id, order_id, correlation_id, idempotency_key, json.dumps(simulate), now, now))
        for i, sd in enumerate(STEPS):
            tx.execute("INSERT INTO saga_steps(saga_id, step_name, ordinal, status, max_attempts, comp_max_attempts,"
                       " updated_at) VALUES (?,?,?,'PENDING',?,?,?)",
                       (saga_id, sd.name, i, self.policy.max_attempts, self.policy.max_attempts, now))
        saga = self._load(tx, saga_id)
        self._event(tx, saga, "SAGA_CREATED", None, "PENDING")
        self._save(tx, saga, S.RUNNING, current_step=STEPS[0].name)
        self._event(tx, saga, "SAGA_STARTED", "PENDING", "RUNNING", STEPS[0].name)
        self._begin_step(tx, saga, STEPS[0].name)
        METRICS.inc("sagaflow_saga_started_total", "Sagas started")
        return saga_id

    def _begin_step(self, tx: Tx, saga: dict, step: str, delay_s: float = 0.0) -> None:
        st = self._steps(tx, saga["id"])[step]
        attempt = st["attempts"] + 1
        self._update_step(tx, saga["id"], step, status="DISPATCHED", attempts=attempt)
        self._send(tx, saga, step, "forward", attempt, delay_s)
        self._event(tx, saga, "STEP_DISPATCHED", saga["state"], saga["state"], step, attempt)

    def _begin_comp(self, tx: Tx, saga: dict, step: str, delay_s: float = 0.0) -> None:
        st = self._steps(tx, saga["id"])[step]
        attempt = st["comp_attempts"] + 1
        self._update_step(tx, saga["id"], step, compensation_status="DISPATCHED", comp_attempts=attempt)
        self._send(tx, saga, step, "compensate", attempt, delay_s)
        METRICS.inc("sagaflow_compensation_attempts_total", "Compensation commands dispatched", step=step)
        self._event(tx, saga, "COMPENSATION_DISPATCHED", saga["state"], saga["state"], step, attempt, comp="DISPATCHED")
        self._save(tx, saga, current_step=step)

    # ------------------------------------------------------------------ replies
    def handle_reply(self, env: Envelope) -> None:
        """Process one reply from a service. Idempotent: duplicates and stale replies are ignored."""
        with self.db.transaction() as tx:
            if tx.one("SELECT 1 AS x FROM processed_messages WHERE message_id=? AND consumer=?",
                      (env.message_id, self.CONSUMER)):
                METRICS.inc("sagaflow_duplicate_messages_total", "Duplicate deliveries ignored", service="orchestrator")
                return
            tx.execute("INSERT INTO processed_messages(message_id, consumer, processed_at) VALUES (?,?,?)",
                       (env.message_id, self.CONSUMER, self._now()))
            saga = self._load(tx, env.saga_id)
            p = env.payload
            if p["action"] == "forward":
                self._on_forward(tx, saga, p)
            else:
                self._on_compensation(tx, saga, p)

    def _ignore(self, tx, saga, p, why: str) -> None:
        self._event(tx, saga, f"REPLY_IGNORED_{why}", saga["state"], saga["state"], p["step"], p.get("attempt", 0))

    def _on_forward(self, tx: Tx, saga: dict, p: dict) -> None:
        step = p["step"]
        st = self._steps(tx, saga["id"])[step]
        if saga["state"] != S.RUNNING.value or st["status"] != "DISPATCHED":
            return self._ignore(tx, saga, p, "STALE")
        if p["status"] == "SUCCEEDED":
            self._update_step(tx, saga["id"], step, status="COMPLETED", last_error=None)
            self._event(tx, saga, "STEP_COMPLETED", "RUNNING", "RUNNING", step, p["attempt"])
            nxt = self._next_step(step)
            if nxt is None:
                self._save(tx, saga, S.COMPLETED, error_code=None, error_detail=None)
                self._event(tx, saga, "SAGA_COMPLETED", "RUNNING", "COMPLETED", step)
                METRICS.inc("sagaflow_saga_completed_total", "Sagas completed")
                self._observe_duration(saga)
            else:
                self._save(tx, saga, current_step=nxt)
                self._begin_step(tx, saga, nxt)
            return
        err = f"{p.get('error_code')}: {p.get('error_detail')}"
        if p.get("retryable"):
            if p["attempt"] < st["attempts"]:
                return self._ignore(tx, saga, p, "OLD_ATTEMPT")
            if self.policy.should_retry(st["attempts"], True, st["max_attempts"]):
                self._schedule_retry(tx, saga, step, st, err)
                return
            # retries exhausted and the outcome cannot be proven -> represent the uncertainty explicitly
            self._update_step(tx, saga["id"], step, status="UNKNOWN", last_error=err)
            self._event(tx, saga, "STEP_OUTCOME_UNKNOWN", "RUNNING", "REQUIRES_ATTENTION", step, st["attempts"], err)
            self._save(tx, saga, S.REQUIRES_ATTENTION, error_code="OUTCOME_UNKNOWN", error_detail=err)
            self._event(tx, saga, "SAGA_REQUIRES_ATTENTION", "RUNNING", "REQUIRES_ATTENTION", step, st["attempts"], err)
            METRICS.inc("sagaflow_saga_requires_attention_total", "Sagas needing an operator")
            return
        self._update_step(tx, saga["id"], step, status="FAILED", last_error=err)
        self._event(tx, saga, "STEP_FAILED", "RUNNING", "RUNNING", step, p["attempt"], err)
        self._start_compensation(tx, saga, err, p.get("error_code"))

    @staticmethod
    def _next_step(step: str) -> str | None:
        names = [s.name for s in STEPS]
        i = names.index(step)
        return names[i + 1] if i + 1 < len(names) else None

    def _schedule_retry(self, tx: Tx, saga: dict, step: str, st: dict, err: str) -> None:
        delay = self.policy.delay(st["attempts"])
        self._update_step(tx, saga["id"], step, last_error=err)
        self._event(tx, saga, "STEP_RETRY_SCHEDULED", saga["state"], saga["state"], step, st["attempts"], err)
        self._save(tx, saga, retry_count=saga["retry_count"] + 1)
        METRICS.inc("sagaflow_saga_retries_total", "Step retries scheduled", step=step)
        self._begin_step(tx, saga, step, delay)

    def _start_compensation(self, tx: Tx, saga: dict, err: str, code: str | None) -> None:
        steps = self._steps(tx, saga["id"])
        plan = compensation_plan({n: s["status"] for n, s in steps.items()})
        METRICS.inc("sagaflow_saga_failures_total", "Sagas that hit a business failure", error=code or "UNKNOWN")
        if not plan:
            self._save(tx, saga, S.FAILED, error_code=code, error_detail=err)
            self._event(tx, saga, "SAGA_FAILED", "RUNNING", "FAILED", saga.get("current_step"), 0, err, "NOT_REQUIRED")
            self._observe_duration(saga)
            return
        for n in plan:
            self._update_step(tx, saga["id"], n, compensation_status="PENDING")
        self._save(tx, saga, S.COMPENSATING, error_code=code, error_detail=err)
        self._event(tx, saga, "COMPENSATION_STARTED", "RUNNING", "COMPENSATING", plan[0], 0, err, "PENDING")
        self._begin_comp(tx, saga, plan[0])

    def _on_compensation(self, tx: Tx, saga: dict, p: dict) -> None:
        step = p["step"]
        st = self._steps(tx, saga["id"])[step]
        if saga["state"] != S.COMPENSATING.value or st["compensation_status"] != "DISPATCHED":
            return self._ignore(tx, saga, p, "STALE")
        if p["status"] == "SUCCEEDED":
            self._update_step(tx, saga["id"], step, compensation_status="COMPLETED")
            self._event(tx, saga, "COMPENSATION_COMPLETED", "COMPENSATING", "COMPENSATING", step, p["attempt"], comp="COMPLETED")
            steps = self._steps(tx, saga["id"])
            pending = [n for n in compensation_plan({k: "COMPLETED" for k in steps})
                       if steps[n]["compensation_status"] == "PENDING"]
            if pending:
                return self._begin_comp(tx, saga, pending[0])
            self._save(tx, saga, S.COMPENSATED)
            self._event(tx, saga, "SAGA_COMPENSATED", "COMPENSATING", "COMPENSATED", step, comp="COMPLETED")
            self._observe_duration(saga)
            return
        err = f"{p.get('error_code')}: {p.get('error_detail')}"
        if p.get("retryable") and p["attempt"] < st["comp_attempts"]:
            return self._ignore(tx, saga, p, "OLD_ATTEMPT")
        if self.policy.should_retry(st["comp_attempts"], bool(p.get("retryable")), st["comp_max_attempts"]):
            self._update_step(tx, saga["id"], step, last_error=err)
            self._save(tx, saga, retry_count=saga["retry_count"] + 1)
            self._event(tx, saga, "COMPENSATION_RETRY_SCHEDULED", "COMPENSATING", "COMPENSATING", step,
                        st["comp_attempts"], err, "DISPATCHED")
            return self._begin_comp(tx, saga, step, self.policy.delay(st["comp_attempts"]))
        # compensation failed: NEVER mark COMPENSATED; keep everything needed for recovery
        self._update_step(tx, saga["id"], step, compensation_status="FAILED", last_error=err)
        self._event(tx, saga, "COMPENSATION_FAILED", "COMPENSATING", "REQUIRES_ATTENTION",
                    step, st["comp_attempts"], err, "FAILED")
        self._save(tx, saga, S.REQUIRES_ATTENTION, error_code="COMPENSATION_FAILED", error_detail=err)
        METRICS.inc("sagaflow_compensation_failures_total", "Compensation failures", step=step)
        METRICS.inc("sagaflow_saga_requires_attention_total", "Sagas needing an operator")

    def _observe_duration(self, saga: dict) -> None:
        from shared.timeutil import parse
        secs = (self.clock.now() - parse(saga["created_at"])).total_seconds()
        METRICS.observe("sagaflow_workflow_duration_seconds", secs, "Saga duration", outcome=saga["state"])

    # ------------------------------------------------------------------ operator actions
    def retry(self, saga_id: str, clear_simulation: bool = False) -> dict:
        """Manual retry for a REQUIRES_ATTENTION saga: re-dispatch the stuck operation with a fresh attempt
        budget. Safe because every service operation is idempotent by (saga, step, action)."""
        with self.db.transaction() as tx:
            saga = self._load(tx, saga_id)
            if saga["state"] != S.REQUIRES_ATTENTION.value:
                raise NotEligible(f"saga is {saga['state']}; only REQUIRES_ATTENTION sagas can be retried")
            steps = self._steps(tx, saga_id)
            if clear_simulation:
                self._save(tx, saga, simulate_json="{}")
            comp = next((s for s in steps.values() if s["compensation_status"] == "FAILED"), None)
            if comp:
                self._update_step(tx, saga_id, comp["step_name"],
                                  comp_max_attempts=comp["comp_attempts"] + self.policy.max_attempts)
                self._save(tx, saga, S.COMPENSATING, error_code=None, error_detail=None)
                self._event(tx, saga, "MANUAL_RETRY", "REQUIRES_ATTENTION", "COMPENSATING",
                            comp["step_name"], comp["comp_attempts"] + 1, comp="DISPATCHED")
                self._begin_comp(tx, saga, comp["step_name"])
            else:
                unk = next((s for s in steps.values() if s["status"] == "UNKNOWN"), None)
                if unk is None:
                    raise NotEligible("no failed operation found to retry")
                self._update_step(tx, saga_id, unk["step_name"], max_attempts=unk["attempts"] + self.policy.max_attempts)
                self._save(tx, saga, S.RUNNING, error_code=None, error_detail=None, current_step=unk["step_name"])
                self._event(tx, saga, "MANUAL_RETRY", "REQUIRES_ATTENTION", "RUNNING", unk["step_name"], unk["attempts"] + 1)
                self._begin_step(tx, saga, unk["step_name"])
            return dict(saga)

    def recover(self, saga_id: str, stale_after_s: float = 0.0) -> bool:
        """Re-dispatch the in-flight operation of an interrupted saga. Returns False if nothing to do."""
        with self.db.transaction() as tx:
            saga = self._load(tx, saga_id)
            if saga["state"] not in {s.value for s in IN_FLIGHT}:
                raise NotEligible(f"saga is {saga['state']}; only RUNNING/COMPENSATING sagas can be recovered")
            return self._redispatch(tx, saga, stale_after_s)

    def _redispatch(self, tx: Tx, saga: dict, stale_after_s: float) -> bool:
        from shared.timeutil import parse
        if (self.clock.now() - parse(saga["updated_at"])).total_seconds() < stale_after_s:
            return False
        if tx.one("SELECT 1 AS x FROM outbox_events WHERE saga_id=? AND status='PENDING'", (saga["id"],)):
            return False  # a command is still waiting in the outbox; the relay will deliver it
        steps = self._steps(tx, saga["id"]).values()
        if saga["state"] == S.RUNNING.value:
            st = next((s for s in steps if s["status"] == "DISPATCHED"), None)
            action, attempt = "forward", st["attempts"] if st else 0
        else:
            st = next((s for s in steps if s["compensation_status"] == "DISPATCHED"), None)
            action, attempt = "compensate", st["comp_attempts"] if st else 0
        if st is None:
            return False
        self._send(tx, saga, st["step_name"], action, attempt)  # same idempotency key => no duplicate effect
        self._event(tx, saga, "SAGA_RECOVERED_REDISPATCH", saga["state"], saga["state"], st["step_name"], attempt)
        self._save(tx, saga)
        METRICS.inc("sagaflow_saga_recoveries_total", "Interrupted sagas re-dispatched")
        return True

    def recover_stale(self, stale_after_s: float | None = None) -> list[str]:
        """Startup / periodic sweep: re-dispatch every in-flight saga that has made no progress."""
        threshold = self.stale_default if stale_after_s is None else stale_after_s
        cutoff = iso(add_seconds(self.clock.now(), -threshold))
        with self.db.read() as tx:
            ids = [r["id"] for r in tx.all("SELECT id FROM sagas WHERE state IN ('RUNNING','COMPENSATING')"
                                           " AND updated_at<=? ORDER BY updated_at", (cutoff,))]
        recovered = []
        for sid in ids:
            with self.db.transaction() as tx:
                saga = self._load(tx, sid)
                if saga["state"] in ("RUNNING", "COMPENSATING") and self._redispatch(tx, saga, threshold):
                    recovered.append(sid)
        return recovered

    stale_default: float = 60.0
