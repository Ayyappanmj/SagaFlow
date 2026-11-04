"""Workflow definition: the ordered steps and the command / compensation for each."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    name: str
    service: str
    forward: str  # command type
    compensate: str  # compensating command type


STEPS: list[StepDef] = [
    StepDef("RESERVE_INVENTORY", "inventory", "inventory.reserve", "inventory.release"),
    StepDef("PROCESS_PAYMENT", "payment", "payment.authorize", "payment.void"),
    StepDef("ARRANGE_SHIPPING", "shipping", "shipping.create", "shipping.cancel"),
]
BY_NAME = {s.name: s for s in STEPS}


def compensation_plan(step_status: dict[str, str]) -> list[str]:
    """Steps to undo, in REVERSE order: only those whose forward action COMPLETED.
    A failed / unknown step is never 'undone' blindly (e.g. no refund for a payment that never happened)."""
    return [s.name for s in reversed(STEPS) if step_status.get(s.name) == "COMPLETED"]
