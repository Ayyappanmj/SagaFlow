"""Broker abstraction. InMemoryBroker (tests) and RabbitMQBroker (pika; used by Docker Compose).

Consumption is poll-based (`get`) with explicit ack: simple, thread-friendly, and the same code path
for both brokers. Topology per queue Q: Q, Q.retry (TTL -> back to Q), Q.dlq (dead letters).
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field

QUEUES = ["inventory.commands", "payment.commands", "shipping.commands", "orchestrator.replies"]


class BrokerUnavailable(Exception):
    pass


@dataclass
class Delivery:
    queue: str
    body: bytes
    headers: dict
    tag: int = 0

    @property
    def attempt(self) -> int:
        return int(self.headers.get("x-attempt", 1))


class InMemoryBroker:
    def __init__(self):
        self._lock = threading.Lock()
        self.queues: dict[str, deque] = defaultdict(deque)
        self.unacked: dict[int, Delivery] = {}
        self.dlq: dict[str, list[tuple[bytes, dict]]] = defaultdict(list)
        self.available = True
        self._tag = 0
        self.published_count = 0

    def declare_topology(self) -> None:
        pass

    def _check(self):
        if not self.available:
            raise BrokerUnavailable("broker unavailable (simulated)")

    def publish(self, queue: str, body: bytes, headers: dict | None = None) -> None:
        with self._lock:
            self._check()
            self.queues[queue].append((body, dict(headers or {})))
            self.published_count += 1

    def get(self, queue: str) -> Delivery | None:
        with self._lock:
            self._check()
            if not self.queues[queue]:
                return None
            body, headers = self.queues[queue].popleft()
            self._tag += 1
            d = Delivery(queue, body, headers, self._tag)
            self.unacked[d.tag] = d
            return d

    def ack(self, d: Delivery) -> None:
        with self._lock:
            self._check()
            self.unacked.pop(d.tag, None)

    def retry(self, d: Delivery) -> None:
        with self._lock:
            self.unacked.pop(d.tag, None)
            self.queues[d.queue].append((d.body, {**d.headers, "x-attempt": d.attempt + 1}))

    def dead_letter(self, d: Delivery, reason: str) -> None:
        with self._lock:
            self.unacked.pop(d.tag, None)
            self.dlq[d.queue].append((d.body, {**d.headers, "x-death-reason": reason}))

    def requeue_unacked(self) -> int:
        """Simulate a consumer dying before ack: the broker redelivers unacked messages."""
        with self._lock:
            n = len(self.unacked)
            for d in sorted(self.unacked.values(), key=lambda x: -x.tag):
                self.queues[d.queue].appendleft((d.body, {**d.headers, "x-redelivered": True}))
            self.unacked.clear()
            return n

    def depth(self, queue: str) -> int:
        return len(self.queues[queue])

    def dlq_messages(self, limit: int = 50) -> list[dict]:
        out = []
        for q, msgs in self.dlq.items():
            for body, headers in msgs:
                out.append({"queue": q, "body": body.decode(), "reason": headers.get("x-death-reason")})
        return out[:limit]

    def ping(self) -> bool:
        return self.available


class RabbitMQBroker:  # pragma: no cover - requires a live RabbitMQ (not executed in the build sandbox)
    EXCHANGE = "sagaflow"
    DLX = "sagaflow.dlx"

    def __init__(self, url: str, retry_delay_ms: int = 5000):
        self.url = url
        self.retry_delay_ms = retry_delay_ms
        self._local = threading.local()

    def _channel(self):
        import pika
        ch = getattr(self._local, "ch", None)
        if ch is not None and ch.is_open:
            return ch
        try:
            conn = pika.BlockingConnection(pika.URLParameters(self.url))
            ch = conn.channel()
            ch.confirm_delivery()  # publish raises unless the broker confirms
        except Exception as e:  # reconnect happens lazily on the next call
            raise BrokerUnavailable(str(e)) from e
        self._local.conn, self._local.ch = conn, ch
        return ch

    def _wrap(self, fn):
        import pika
        try:
            return fn(self._channel())
        except (pika.exceptions.AMQPError, OSError) as e:
            self._local.ch = None
            raise BrokerUnavailable(str(e)) from e

    def declare_topology(self) -> None:
        def go(ch):
            ch.exchange_declare(self.EXCHANGE, "direct", durable=True)
            ch.exchange_declare(self.DLX, "direct", durable=True)
            for q in QUEUES:
                ch.queue_declare(q, durable=True, arguments={
                    "x-dead-letter-exchange": self.DLX, "x-dead-letter-routing-key": q + ".dlq"})
                ch.queue_declare(q + ".dlq", durable=True)
                ch.queue_declare(q + ".retry", durable=True, arguments={
                    "x-message-ttl": self.retry_delay_ms,
                    "x-dead-letter-exchange": self.EXCHANGE, "x-dead-letter-routing-key": q})
                ch.queue_bind(q, self.EXCHANGE, q)
                ch.queue_bind(q + ".dlq", self.DLX, q + ".dlq")
        self._wrap(go)

    def _pub(self, ch, exchange, key, body, headers):
        import pika
        ch.basic_publish(exchange, key, body, pika.BasicProperties(delivery_mode=2, headers=headers))

    def publish(self, queue, body, headers=None):
        self._wrap(lambda ch: self._pub(ch, self.EXCHANGE, queue, body, headers or {}))

    def get(self, queue):
        def go(ch):
            m, props, body = ch.basic_get(queue, auto_ack=False)
            if m is None:
                return None
            return Delivery(queue, body, dict(props.headers or {}), m.delivery_tag)
        return self._wrap(go)

    def ack(self, d):
        self._wrap(lambda ch: ch.basic_ack(d.tag))

    def retry(self, d):
        def go(ch):
            self._pub(ch, "", d.queue + ".retry", d.body, {**d.headers, "x-attempt": d.attempt + 1})
            ch.basic_ack(d.tag)
        self._wrap(go)

    def dead_letter(self, d, reason):
        def go(ch):
            self._pub(ch, self.DLX, d.queue + ".dlq", d.body, {**d.headers, "x-death-reason": reason})
            ch.basic_ack(d.tag)
        self._wrap(go)

    def depth(self, queue):
        return self._wrap(lambda ch: ch.queue_declare(queue, passive=True).method.message_count)

    def dlq_messages(self, limit=50):
        out = []

        def go(ch):
            for q in QUEUES:
                for _ in range(limit):
                    m, props, body = ch.basic_get(q + ".dlq", auto_ack=False)
                    if m is None:
                        break
                    out.append({"queue": q, "body": body.decode(),
                                "reason": (props.headers or {}).get("x-death-reason")})
                    ch.basic_nack(m.delivery_tag, requeue=True)
        self._wrap(go)
        return out[:limit]

    def ping(self):
        try:
            self._wrap(lambda ch: None)
            return True
        except BrokerUnavailable:
            return False
