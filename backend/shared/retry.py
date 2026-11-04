"""Retry policy (exponential backoff) and error classification."""
from __future__ import annotations

from dataclasses import dataclass

RETRYABLE_CODES = {"TIMEOUT", "SERVICE_UNAVAILABLE", "DB_TRANSIENT"}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 1.0
    factor: float = 2.0
    max_delay_s: float = 60.0

    def delay(self, attempt: int) -> float:
        """Delay before attempt N+1, given that attempt N just failed (attempt >= 1)."""
        return min(self.max_delay_s, self.base_delay_s * self.factor ** (attempt - 1))

    def should_retry(self, attempt: int, retryable: bool, max_attempts: int | None = None) -> bool:
        return retryable and attempt < (max_attempts or self.max_attempts)


def is_retryable_code(code: str | None) -> bool:
    return code in RETRYABLE_CODES
