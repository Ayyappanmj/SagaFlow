"""Public REST API / gateway. Reads sagas from the orchestrator DB, creates orders (order+saga+outbox in one
transaction), proxies read-only queries to the business services over HTTP. (FastAPI: not executed in sandbox.)"""
from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orchestrator import queries
from orchestrator.engine import NotEligible, SagaEngine, SagaNotFound
from orchestrator.orders import IdempotencyConflict, ValidationError, create_order
from shared.app_factory import build_broker, error_body, install_common
from shared.config import Settings
from shared.db import Database
from shared.logging_setup import setup_logging
from shared.migrate import apply_migrations
from shared.retry import RetryPolicy


class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=1000)
    unit_price_cents: int = Field(ge=0, le=10_000_000)


class OrderIn(BaseModel):
    customer_ref: str = Field(min_length=1, max_length=128)
    items: list[ItemIn] = Field(min_length=1, max_length=50)
    simulate: dict | None = Field(default=None, description="DEV ONLY failure scenario; ignored unless dev mode")


class ActionIn(BaseModel):
    clear_simulation: bool = False


class ScenarioIn(BaseModel):
    simulate: dict
    sticky: bool = False


def create_app(settings: Settings | None = None, db: Database | None = None, broker=None) -> FastAPI:
    s = settings or Settings()
    setup_logging("api")
    db = db or Database(s.orchestrator_db)
    broker = broker or build_broker(s)
    engine = SagaEngine(db, RetryPolicy(s.max_attempts, s.retry_base_delay_s))

    @asynccontextmanager
    async def lifespan(app):
        apply_migrations(db, "orchestrator")
        yield

    app = FastAPI(title="SagaFlow API", version="1.0.0", lifespan=lifespan)
    app.state.next_simulate, app.state.sticky = None, False
    install_common(app, "api", {"database": db.ping, "broker": broker.ping})

    def admin(x_admin_token: str | None = Header(default=None)):
        if s.admin_token:
            if not x_admin_token or not hmac.compare_digest(x_admin_token, s.admin_token):
                raise HTTPException(401, "admin token required")
        elif not s.dev_mode:
            raise HTTPException(403, "admin operations are disabled: set ADMIN_TOKEN")

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT"}.get(exc.status_code, "ERROR")
        return JSONResponse(error_body(code, str(exc.detail), getattr(request.state, "request_id", "")), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def val_exc(request: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return JSONResponse(error_body("VALIDATION_ERROR", msg, getattr(request.state, "request_id", "")), 422)

    @app.post("/api/v1/orders", status_code=201)
    def post_order(body: OrderIn, request: Request, idempotency_key: str = Header(min_length=8, max_length=128)):
        sim = None
        if s.dev_mode:
            sim = body.simulate or app.state.next_simulate
            if app.state.next_simulate and not app.state.sticky and not body.simulate:
                app.state.next_simulate = None
        req = body.model_dump(exclude={"simulate"})
        try:
            resp, created = create_order(db, engine, req, idempotency_key, request.state.correlation_id, sim)
        except IdempotencyConflict as e:
            raise HTTPException(409, str(e)) from e
        except ValidationError as e:
            raise HTTPException(422, str(e)) from e
        return JSONResponse(resp, 201 if created else 200)

    @app.get("/api/v1/orders")
    def get_orders(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return queries.list_orders(db, limit, offset)

    @app.get("/api/v1/orders/{order_id}")
    def get_order(order_id: str):
        o = queries.get_order(db, order_id)
        if o is None:
            raise HTTPException(404, "order not found")
        return o

    @app.get("/api/v1/sagas")
    def get_sagas(state: str | None = None, q: str | None = None, limit: int = Query(20, ge=1, le=100),
                  offset: int = Query(0, ge=0)):
        return queries.list_sagas(db, state, q, limit, offset)

    @app.get("/api/v1/sagas/{saga_id}")
    def get_saga(saga_id: str):
        r = queries.get_saga(db, saga_id)
        if r is None:
            raise HTTPException(404, "saga not found")
        return r

    @app.get("/api/v1/sagas/{saga_id}/history")
    def get_history(saga_id: str):
        r = queries.get_history(db, saga_id)
        if r is None:
            raise HTTPException(404, "saga not found")
        return {"items": r}

    @app.post("/api/v1/sagas/{saga_id}/retry", dependencies=[Depends(admin)])
    def retry(saga_id: str, body: ActionIn | None = None):
        try:
            engine.retry(saga_id, bool(body and body.clear_simulation and s.dev_mode))
        except SagaNotFound as e:
            raise HTTPException(404, "saga not found") from e
        except NotEligible as e:
            raise HTTPException(409, str(e)) from e
        return queries.get_saga(db, saga_id)

    @app.post("/api/v1/sagas/{saga_id}/recover", dependencies=[Depends(admin)])
    def recover(saga_id: str):
        try:
            ok = engine.recover(saga_id)
        except SagaNotFound as e:
            raise HTTPException(404, "saga not found") from e
        except NotEligible as e:
            raise HTTPException(409, str(e)) from e
        if not ok:
            raise HTTPException(409, "no in-flight operation eligible for recovery")
        return queries.get_saga(db, saga_id)

    @app.post("/api/v1/dev/failure-scenarios")
    def set_scenario(body: ScenarioIn):
        if not s.dev_mode:
            raise HTTPException(404, "not found")  # invisible outside development
        app.state.next_simulate, app.state.sticky = body.simulate, body.sticky
        return {"armed": body.simulate, "sticky": body.sticky}

    @app.get("/api/v1/stats")
    def get_stats():
        st = queries.stats(db)
        try:
            st["queue_backlog"] = {q: broker.depth(q) for q in ("inventory.commands", "payment.commands",
                                                              "shipping.commands", "orchestrator.replies")}
        except Exception:  # noqa: BLE001
            st["queue_backlog"] = None
        return st

    @app.get("/api/v1/dead-letters")
    def dead_letters():
        try:
            return {"items": broker.dlq_messages()}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, "broker unavailable") from e

    def proxy(name: str, url: str, path: str):
        try:
            r = httpx.get(f"{url}{path}", timeout=3)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"{name} service unavailable") from e

    @app.get("/api/v1/inventory")
    def inventory():
        return proxy("inventory", s.inventory_url, "/api/v1/inventory")

    @app.get("/api/v1/payments")
    def payments():
        return proxy("payment", s.payment_url, "/api/v1/payments")

    @app.get("/api/v1/shipments")
    def shipments():
        return proxy("shipping", s.shipping_url, "/api/v1/shipments")

    @app.get("/api/v1/system-health")
    def system_health():
        out = {}
        for name, url in (("inventory", s.inventory_url), ("payment", s.payment_url), ("shipping", s.shipping_url),
                          ("orchestrator", s.orchestrator_url)):
            try:
                r = httpx.get(f"{url}/api/v1/ready", timeout=2)
                out[name] = {"up": True, "ready": r.status_code == 200, "checks": r.json().get("checks")}
            except Exception:  # noqa: BLE001
                out[name] = {"up": False, "ready": False, "checks": None}
        out["api"] = {"up": True, "ready": db.ping() and broker.ping(), "checks": {"database": db.ping(), "broker": broker.ping()}}
        return out

    return app


def get_app() -> FastAPI:  # uvicorn api.app:get_app --factory
    return create_app()
