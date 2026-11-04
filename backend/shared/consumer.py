"""Consumer: ack only after the handler's DB transaction committed; bounded retries; DLQ for poison messages."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .broker import BrokerUnavailable
from .messages import Envelope, SchemaError
from .metrics import METRICS

logger = logging.getLogger("consumer")


class NonRetryableError(Exception):
    """Handler failure that retrying cannot fix (goes straight to the DLQ)."""


class Consumer:
    def __init__(self, broker, queue: str, handler: Callable[[Envelope], None],
                 max_attempts: int = 5, name: str | None = None):
        self.broker, self.queue, self.handler = broker, queue, handler
        self.max_attempts, self.name = max_attempts, name or queue

    def poll_once(self) -> bool:
        d = self.broker.get(self.queue)
        if d is None:
            return False
        try:
            env = Envelope.from_json(d.body)
            self.handler(env)
        except (SchemaError, NonRetryableError) as e:
            self.broker.dead_letter(d, f"non-retryable: {e}")
            METRICS.inc("sagaflow_messages_dead_lettered_total", "Dead-lettered messages", queue=self.queue)
            logger.error("dead-lettered %s: %s", self.queue, e)
        except Exception as e:  # noqa: BLE001 - any handler failure is retried (bounded)
            METRICS.inc("sagaflow_message_processing_failures_total", "Handler failures", queue=self.queue)
            if d.attempt >= self.max_attempts:
                self.broker.dead_letter(d, f"max attempts exceeded: {type(e).__name__}")
                METRICS.inc("sagaflow_messages_dead_lettered_total", "Dead-lettered messages", queue=self.queue)
            else:
                self.broker.retry(d)
                METRICS.inc("sagaflow_message_retries_total", "Message retries", queue=self.queue)
            logger.warning("handler failed attempt=%s queue=%s: %s", d.attempt, self.queue, type(e).__name__)
        else:
            self.broker.ack(d)  # ack strictly AFTER durable processing
        return True

    def run(self, stop: threading.Event, idle_sleep: float = 0.1) -> None:
        backoff = 0.5
        while not stop.is_set():  # finishing the current message before exiting = graceful shutdown
            try:
                busy = self.poll_once()
                backoff = 0.5
                if not busy:
                    stop.wait(idle_sleep)
            except BrokerUnavailable as e:  # reconnect loop
                logger.warning("broker unavailable (%s); retrying in %.1fs", e, backoff)
                stop.wait(backoff)
                backoff = min(backoff * 2, 15)


def run_loop(fn: Callable[[], object], stop: threading.Event, interval: float) -> None:
    while not stop.is_set():
        try:
            fn()
        except Exception:  # noqa: BLE001
            logger.exception("background loop error")
        stop.wait(interval)


def start_thread(target, *args) -> threading.Thread:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


__all__ = ["Consumer", "NonRetryableError", "run_loop", "start_thread", "time"]
