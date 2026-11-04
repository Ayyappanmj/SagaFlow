"""Helpers for tests requiring live PostgreSQL and RabbitMQ."""
from __future__ import annotations

import os

from shared.broker import RabbitMQBroker
from shared.db import Database
from shared.migrate import apply_migrations

import socket

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = os.getenv("POSTGRES_PORT", "5432")
PG_USER = os.getenv("POSTGRES_USER", "sagaflow")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "sagaflow_dev_only")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", f"amqp://{PG_USER}:{PG_PASS}@{PG_HOST}:5672/")


def _tcp_ping(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pg_url(db_name: str) -> str:
    return os.getenv(f"{db_name.upper()}_DB_URL", f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{db_name}")


def check_postgres() -> bool:
    if not _tcp_ping(PG_HOST, int(PG_PORT)):
        return False
    try:
        db = Database(pg_url("inventory"))
        return db.ping()
    except Exception:
        return False


def check_rabbitmq() -> bool:
    if not _tcp_ping(PG_HOST, 5672):
        return False
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
