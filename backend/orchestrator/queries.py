"""Read models for the API / dashboard."""
from __future__ import annotations

from shared.db import Database


def get_order(db: Database, order_id: str) -> dict | None:
    with db.read() as tx:
        o = tx.one("SELECT * FROM orders WHERE id=?", (order_id,))
        if o is None:
            return None
        o["items"] = tx.all("SELECT sku, quantity, unit_price_cents FROM order_items WHERE order_id=? ORDER BY sku", (order_id,))
        s = tx.one("SELECT id, state FROM sagas WHERE order_id=?", (order_id,))
        o["saga_id"], o["saga_state"] = (s["id"], s["state"]) if s else (None, None)
        return o


def list_orders(db: Database, limit: int = 20, offset: int = 0) -> dict:
    with db.read() as tx:
        total = tx.one("SELECT COUNT(*) AS n FROM orders")["n"]
        rows = tx.all("SELECT o.id, o.customer_ref, o.status, o.total_cents, o.created_at, s.id AS saga_id"
                      " FROM orders o LEFT JOIN sagas s ON s.order_id=o.id ORDER BY o.created_at DESC, o.id LIMIT ? OFFSET ?",
                      (limit, offset))
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def list_sagas(db: Database, state: str | None, q: str | None, limit: int, offset: int) -> dict:
    where, params = [], []
    if state:
        where.append("state=?"); params.append(state)
    if q:
        where.append("(id=? OR order_id=?)"); params += [q, q]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with db.read() as tx:
        total = tx.one(f"SELECT COUNT(*) AS n FROM sagas {w}", tuple(params))["n"]
        rows = tx.all(f"SELECT id, order_id, state, current_step, retry_count, error_code, created_at, updated_at, version"
                      f" FROM sagas {w} ORDER BY created_at DESC, id LIMIT ? OFFSET ?", (*params, limit, offset))
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def get_saga(db: Database, saga_id: str) -> dict | None:
    with db.read() as tx:
        s = tx.one("SELECT * FROM sagas WHERE id=?", (saga_id,))
        if s is None:
            return None
        s.pop("simulate_json", None)  # dev-only detail, not exposed
        s["steps"] = tx.all("SELECT step_name, status, compensation_status, attempts, max_attempts, comp_attempts,"
                            " last_error, updated_at FROM saga_steps WHERE saga_id=? ORDER BY ordinal", (saga_id,))
        s["pending_outbox"] = tx.one(
            "SELECT COUNT(*) AS n FROM outbox_events WHERE saga_id=? AND status='PENDING'", (saga_id,)
        )["n"]
        return s


def get_history(db: Database, saga_id: str) -> list[dict] | None:
    with db.read() as tx:
        if tx.one("SELECT 1 AS x FROM sagas WHERE id=?", (saga_id,)) is None:
            return None
        return tx.all("SELECT seq, step_name, previous_state, new_state, event_type, attempt, error_detail,"
                      " compensation_status, created_at FROM saga_events WHERE saga_id=? ORDER BY seq", (saga_id,))


def stats(db: Database) -> dict:
    with db.read() as tx:
        by_state = {r["state"]: r["n"] for r in tx.all("SELECT state, COUNT(*) AS n FROM sagas GROUP BY state")}
        orders = tx.one("SELECT COUNT(*) AS n FROM orders")["n"]
        retries = tx.one("SELECT COALESCE(SUM(retry_count),0) AS n FROM sagas")["n"]
        pending = tx.one("SELECT COUNT(*) AS n FROM outbox_events WHERE status='PENDING'")["n"]
        done = tx.all(
            "SELECT created_at, completed_at FROM sagas WHERE completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 500"
        )
    from shared.timeutil import parse
    durs = [(parse(r["completed_at"]) - parse(r["created_at"])).total_seconds() for r in done]
    return {"total_orders": orders, "sagas_by_state": by_state, "total_retries": retries,
            "pending_outbox": pending, "avg_workflow_seconds": (sum(durs) / len(durs)) if durs else None}
