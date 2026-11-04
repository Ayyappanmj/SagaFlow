"""Order creation with idempotency. Order + saga + first outbox command + idempotency record are ONE transaction."""
from __future__ import annotations

import hashlib
import json
import uuid

from shared.db import Database, IntegrityError
from shared.timeutil import Clock

from .engine import SagaEngine


class ValidationError(Exception):
    pass


class IdempotencyConflict(Exception):
    """Same Idempotency-Key reused with a different request body."""


def validate_order(req: dict) -> None:
    items = req.get("items")
    if not req.get("customer_ref") or not isinstance(req.get("customer_ref"), str):
        raise ValidationError("customer_ref is required")
    if not isinstance(items, list) or not items or len(items) > 50:
        raise ValidationError("items must be a list with 1-50 entries")
    for it in items:
        if not isinstance(it.get("sku"), str) or not it["sku"]:
            raise ValidationError("item sku is required")
        if not isinstance(it.get("quantity"), int) or not 0 < it["quantity"] <= 1000:
            raise ValidationError("item quantity must be an integer between 1 and 1000")
        if not isinstance(it.get("unit_price_cents"), int) or it["unit_price_cents"] < 0:
            raise ValidationError("unit_price_cents must be a non-negative integer")


def create_order(db: Database, engine: SagaEngine, req: dict, idempotency_key: str, correlation_id: str,
                 simulate: dict | None = None, clock: Clock | None = None) -> tuple[dict, bool]:
    """Returns (response, created). Replays of the same key+body return the original response."""
    validate_order(req)
    clock = clock or engine.clock
    req_hash = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    for _ in range(2):
        try:
            with db.transaction() as tx:
                rec = tx.one("SELECT request_hash, response_json FROM idempotency_records WHERE key=?", (idempotency_key,))
                if rec:
                    if rec["request_hash"] != req_hash:
                        raise IdempotencyConflict("Idempotency-Key was already used with a different request")
                    return json.loads(rec["response_json"]), False
                oid, now = str(uuid.uuid4()), clock.now_iso()
                total = sum(i["quantity"] * i["unit_price_cents"] for i in req["items"])
                tx.execute("INSERT INTO orders(id, customer_ref, status, total_cents, idempotency_key, created_at, updated_at)"
                           " VALUES (?,?,'PENDING',?,?,?,?)", (oid, req["customer_ref"], total, idempotency_key, now, now))
                for it in req["items"]:
                    tx.execute("INSERT INTO order_items(id, order_id, sku, quantity, unit_price_cents) VALUES (?,?,?,?,?)",
                               (str(uuid.uuid4()), oid, it["sku"], it["quantity"], it["unit_price_cents"]))
                saga_id = engine.create_saga(tx, oid, correlation_id, idempotency_key, simulate or {})
                resp = {"order_id": oid, "saga_id": saga_id, "status": "PENDING", "total_cents": total}
                tx.execute("INSERT INTO idempotency_records(key, request_hash, response_json, created_at) VALUES (?,?,?,?)",
                           (idempotency_key, req_hash, json.dumps(resp), now))
                return resp, True
        except IntegrityError:
            continue  # lost a race with a concurrent identical request: re-read the stored response
    raise RuntimeError("could not create order")
