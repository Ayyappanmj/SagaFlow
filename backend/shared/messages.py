"""Versioned message envelope + schema validation. Invalid messages are never retried (-> DLQ)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1
REPLY_TYPE = "saga.reply"
COMMAND_TYPES = {"inventory.reserve", "inventory.release", "payment.authorize",
                 "payment.void", "shipping.create", "shipping.cancel"}
REQUIRED_PAYLOAD: dict[str, tuple[str, ...]] = {
    **{t: ("order_id", "step", "action", "attempt") for t in COMMAND_TYPES},
    REPLY_TYPE: ("step", "action", "status", "service"),
}


class SchemaError(Exception):
    """Message is malformed: retrying can never help."""


@dataclass
class Envelope:
    type: str
    saga_id: str
    correlation_id: str
    idempotency_key: str
    payload: dict[str, Any]
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = SCHEMA_VERSION
    occurred_at: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_json(raw: str | bytes) -> "Envelope":
        try:
            d = json.loads(raw)
        except (ValueError, TypeError) as e:
            raise SchemaError(f"not valid JSON: {e}") from e
        return validate(d)


def validate(d: Any) -> Envelope:
    if not isinstance(d, dict):
        raise SchemaError("envelope must be an object")
    for k in ("message_id", "type", "version", "saga_id", "correlation_id", "idempotency_key", "payload"):
        if k not in d:
            raise SchemaError(f"missing field: {k}")
    if d["version"] != SCHEMA_VERSION:
        raise SchemaError(f"unsupported schema version {d['version']}")
    required = REQUIRED_PAYLOAD.get(d["type"])
    if required is None:
        raise SchemaError(f"unknown message type {d['type']}")
    if not isinstance(d["payload"], dict):
        raise SchemaError("payload must be an object")
    for k in required:
        if k not in d["payload"]:
            raise SchemaError(f"payload missing field: {k}")
    if d["type"] in COMMAND_TYPES and d["type"] == "inventory.reserve":
        items = d["payload"].get("items")
        if not isinstance(items, list) or not items or any(
                not isinstance(i, dict) or not isinstance(i.get("sku"), str)
                or not isinstance(i.get("quantity"), int) or i["quantity"] <= 0 for i in items):
            raise SchemaError("inventory.reserve requires non-empty items with sku and quantity > 0")
    return Envelope(**{k: d[k] for k in ("type", "saga_id", "correlation_id", "idempotency_key",
                                         "payload", "message_id", "version")},
                    occurred_at=d.get("occurred_at", ""))
