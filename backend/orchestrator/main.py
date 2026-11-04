"""Orchestrator process: reply consumer + outbox relay + crash recovery, with health/metrics endpoints."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.app_factory import build_broker, install_common
from shared.config import Settings
from shared.db import Database
from shared.logging_setup import setup_logging
from shared.migrate import apply_migrations
from shared.retry import RetryPolicy

from .engine import SagaEngine
from .runtime import OrchestratorRuntime

settings = Settings()
setup_logging("orchestrator")
db = Database(settings.orchestrator_db)
broker = build_broker(settings)
engine = SagaEngine(db, RetryPolicy(settings.max_attempts, settings.retry_base_delay_s))
runtime = OrchestratorRuntime(engine, broker, settings.stale_after_s)


@asynccontextmanager
async def lifespan(app):
    apply_migrations(db, "orchestrator")
    runtime.start()  # includes startup crash-recovery
    yield
    runtime.shutdown()


app = FastAPI(title="SagaFlow orchestrator", lifespan=lifespan)
install_common(app, "orchestrator", {"database": db.ping, "broker": broker.ping})
