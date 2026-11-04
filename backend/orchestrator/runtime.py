"""Runs the orchestrator's background work: reply consumer, outbox relay, stale-saga recovery."""
from __future__ import annotations

import threading

from shared.consumer import Consumer, run_loop, start_thread
from shared.outbox import OutboxPublisher

from .engine import SagaEngine


class OrchestratorRuntime:
    def __init__(self, engine: SagaEngine, broker, stale_after_s: float = 60.0):
        self.engine, self.broker = engine, broker
        self.publisher = OutboxPublisher(engine.db, broker, engine.clock, service="orchestrator")
        self.consumer = Consumer(broker, "orchestrator.replies", engine.handle_reply, name="orchestrator")
        self.stale_after_s = stale_after_s
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def startup_recovery(self) -> list[str]:
        """Crash recovery: re-dispatch in-flight sagas whose commands/replies may have been lost.
        Pending outbox rows are simply published by the relay (they are durable in PostgreSQL)."""
        return self.engine.recover_stale(self.stale_after_s)

    def start(self) -> None:
        self.broker.declare_topology()
        self.engine.stale_default = self.stale_after_s
        self.startup_recovery()
        self.threads = [start_thread(self.consumer.run, self.stop),
                        start_thread(run_loop, self.publisher.relay_once, self.stop, 0.2),
                        start_thread(run_loop, lambda: self.engine.recover_stale(self.stale_after_s), self.stop, 15.0)]

    def shutdown(self) -> None:
        self.stop.set()
        for t in self.threads:
            t.join(timeout=5)
