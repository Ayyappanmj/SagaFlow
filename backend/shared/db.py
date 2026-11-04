"""Tiny DB-API wrapper: SQLite (tests / zero-dependency dev) and PostgreSQL (Docker, via psycopg 3).

SQL is written with `?` placeholders and translated for PostgreSQL. Every write goes through
`Database.transaction()`, which opens an explicit transaction (BEGIN IMMEDIATE on SQLite).
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

try:  # optional: only needed for PostgreSQL
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]


class IntegrityError(Exception):
    """Unique / foreign-key / check constraint violation."""


class Tx:
    def __init__(self, conn: Any, is_pg: bool):
        self.conn = conn
        self.is_pg = is_pg

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_pg else sql

    def _run(self, sql: str, params: tuple = ()):
        try:
            return self.conn.execute(self._sql(sql), params)
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except Exception as e:
            if psycopg is not None and isinstance(e, psycopg.errors.IntegrityError):
                raise IntegrityError(str(e)) from e
            raise

    def execute(self, sql: str, params: tuple = ()) -> int:
        return self._run(sql, params).rowcount

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        row = self._run(sql, params).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._run(sql, params).fetchall()]

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        name = "sp_" + uuid.uuid4().hex[:8]
        self.conn.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.conn.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            self.conn.execute(f"RELEASE SAVEPOINT {name}")


class Database:
    def __init__(self, url: str):
        self.url = url
        self.is_pg = url.startswith("postgres")
        self._local = threading.local()

    def _connect(self):
        if self.is_pg:
            if psycopg is None:
                raise RuntimeError("psycopg is required for PostgreSQL URLs")
            return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        path = self.url.replace("sqlite:///", "", 1)
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=60, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self._connect()
        return c

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        conn = self.conn()
        conn.execute("BEGIN" if self.is_pg else "BEGIN IMMEDIATE")
        try:
            yield Tx(conn, self.is_pg)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[Tx]:
        """Read-only access outside an explicit transaction (autocommit)."""
        yield Tx(self.conn(), self.is_pg)

    def ping(self) -> bool:
        try:
            with self.read() as tx:
                tx.one("SELECT 1 AS ok")
            return True
        except Exception:
            return False
