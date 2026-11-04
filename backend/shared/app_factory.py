"""FastAPI helpers shared by all services: request/correlation ids, HTTP metrics, health, /metrics,
and a lifespan that starts/stops the background workers. (Requires fastapi; not executed in the build sandbox.)"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .broker import InMemoryBroker, RabbitMQBroker
from .config import Settings
from .logging_setup import bind, setup_logging
from .metrics import METRICS

MAX_BODY = 64 * 1024


def build_broker(s: Settings):
    return InMemoryBroker() if s.broker == "memory" else RabbitMQBroker(s.rabbitmq_url)


def error_body(code: str, message: str, request_id: str = "") -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def install_common(app: FastAPI, service: str, ready_checks) -> None:
    @app.middleware("http")
    async def mw(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        cid = request.headers.get("X-Correlation-ID") or rid
        bind(request_id=rid, correlation_id=cid)
        request.state.request_id, request.state.correlation_id = rid, cid
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse(error_body("PAYLOAD_TOO_LARGE", "request body too large", rid), 413)
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:  # noqa: BLE001 - never leak stack traces
            resp = JSONResponse(error_body("INTERNAL_ERROR", "unexpected error", rid), 500)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")  # route template => bounded label cardinality
        METRICS.inc("sagaflow_http_requests_total", "HTTP requests", service=service, method=request.method,
                    path=path, status=str(resp.status_code))
        METRICS.observe("sagaflow_http_request_duration_seconds", time.perf_counter() - t0, "HTTP latency",
                        service=service, path=path)
        resp.headers["X-Request-ID"], resp.headers["X-Correlation-ID"] = rid, cid
        return resp

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")

    @app.get("/api/v1/health")
    def health():  # liveness: the process is up
        return {"status": "ok", "service": service}

    @app.get("/api/v1/ready")
    def ready():  # readiness: dependencies reachable
        checks = {name: bool(fn()) for name, fn in ready_checks.items()}
        ok = all(checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, 200 if ok else 503)


def service_app(service: str, svc, settings: Settings, routes=None) -> FastAPI:
    """App for a business service: consumes <service>.commands and relays its own outbox."""
    import threading

    from .consumer import Consumer, run_loop, start_thread
    from .migrate import apply_migrations
    from .outbox import OutboxPublisher

    setup_logging(service)
    broker = build_broker(settings)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app):
        apply_migrations(svc.db, service)
        broker.declare_topology()
        consumer = Consumer(broker, f"{service}.commands", svc.handle, max_attempts=5, name=service)
        pub = OutboxPublisher(svc.db, broker, service=service)
        threads = [start_thread(consumer.run, stop), start_thread(run_loop, pub.relay_once, stop, 0.2)]
        yield
        stop.set()  # graceful: workers finish the current message
        for t in threads:
            t.join(timeout=5)

    app = FastAPI(title=f"SagaFlow {service} service", lifespan=lifespan)
    install_common(app, service, {"database": svc.db.ping, "broker": broker.ping})
    if routes:
        routes(app, svc)
    return app
