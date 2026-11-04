"""Pure saga state machine: which transitions are legal. No I/O here."""
from __future__ import annotations

from enum import StrEnum


class SagaState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"  # failed with nothing to compensate
    REQUIRES_ATTENTION = "REQUIRES_ATTENTION"  # needs an operator (unknown outcome / compensation failed)


S = SagaState
TRANSITIONS: dict[SagaState, set[SagaState]] = {
    S.PENDING: {S.RUNNING, S.FAILED},
    S.RUNNING: {S.COMPLETED, S.COMPENSATING, S.FAILED, S.REQUIRES_ATTENTION},
    S.COMPENSATING: {S.COMPENSATED, S.REQUIRES_ATTENTION},
    S.REQUIRES_ATTENTION: {S.RUNNING, S.COMPENSATING},  # manual retry / recovery only
    S.COMPLETED: set(),
    S.COMPENSATED: set(),
    S.FAILED: set(),
}
TERMINAL = {S.COMPLETED, S.COMPENSATED, S.FAILED}
IN_FLIGHT = {S.RUNNING, S.COMPENSATING}


class InvalidTransition(Exception):
    pass


class ConcurrentModification(Exception):
    """Optimistic-lock failure: someone else updated the saga first. Safe to retry."""


def validate_transition(old: SagaState | str, new: SagaState | str) -> None:
    old, new = SagaState(old), SagaState(new)
    if new not in TRANSITIONS[old]:
        raise InvalidTransition(f"{old.value} -> {new.value} is not allowed")


def order_status_for(state: SagaState) -> str:
    return {S.COMPLETED: "COMPLETED", S.COMPENSATED: "CANCELLED", S.FAILED: "FAILED",
            S.REQUIRES_ATTENTION: "REQUIRES_ATTENTION"}.get(state, "PENDING")
