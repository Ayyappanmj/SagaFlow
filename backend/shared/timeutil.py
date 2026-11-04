"""UTC time helpers. All timestamps are stored as ISO-8601 UTC strings (sortable as text)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT).replace(tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def now_iso(self) -> str:
        return iso(self.now())


class FakeClock(Clock):
    """Deterministic clock for tests (retry backoff, stale detection)."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, dt: datetime) -> None:
        self._now = dt


def add_seconds(dt: datetime, seconds: float) -> datetime:
    return dt + timedelta(seconds=seconds)
