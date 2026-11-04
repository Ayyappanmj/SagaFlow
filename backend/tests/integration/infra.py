"""Helpers for tests requiring live PostgreSQL and RabbitMQ."""
from __future__ import annotations

import os

from shared.broker import RabbitMQBroker
from shared.db import Database
from shared.migrate import apply_migrations

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = os.getenv("POSTGRES_PORT", "5432")
PG_USER = os.getenv("POSTGRES_USER", "sagaflow")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "sagaflow_dev_only")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", f"amqp://{PG_USER}:{PG_PASS}@{PG_HOST}:5672/")


def pg_url(db_name: str) -> str:
    return os.getenv(f"{db_name.upper()}_DB_URL", f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{db_name}")


def check_postgres() -> bool:
    try:
        db = Database(pg_url("inventory"))
        return db.ping()
    except Exception:
        return False


def check_rabbitmq() -> bool:
    try:
        broker = RabbitMQBroker(RABBITMQ_URL)
        return broker.ping()
    except Exception:
        return False


HAVE_PG = check_postgres()
HAVE_RMQ = check_rabbitmq()
HAVE_INFRA = HAVE_PG and HAVE_RMQ


def init_pg_service(service_name: str) -> Database:
    db = Database(pg_url(service_name))
    apply_migrations(db, service_name)
    return db
