"""Minimal forward-only SQL migration runner (versions tracked in schema_migrations)."""
from __future__ import annotations

from pathlib import Path

from .db import Database
from .timeutil import Clock

ROOT = Path(__file__).resolve().parents[2] / "migrations"


def _statements(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def apply_migrations(db: Database, service: str, root: Path = ROOT) -> list[str]:
    """Apply migrations/common then migrations/<service>. Returns the versions newly applied."""
    with db.transaction() as tx:
        tx.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                   "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    applied: list[str] = []
    for d in ("common", service):
        for f in sorted((root / d).glob("*.sql")):
            version = f"{d}/{f.name}"
            with db.transaction() as tx:
                if tx.one("SELECT 1 AS x FROM schema_migrations WHERE version=?", (version,)):
                    continue
                for stmt in _statements(f.read_text()):
                    tx.execute(stmt)
                tx.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)",
                           (version, Clock().now_iso()))
            applied.append(version)
    return applied
