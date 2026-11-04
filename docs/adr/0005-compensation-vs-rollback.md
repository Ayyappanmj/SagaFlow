# ADR 0005: Compensation is not rollback

**Context.** Each service commits locally; there is no global rollback.

**Options considered.** 2PC/XA; saga with compensations.

**Decision.** Explicit compensating commands (release, void, cancel) executed in reverse order, themselves idempotent and retried; failures end in `REQUIRES_ATTENTION`.

**Advantages.** Works across independent databases and brokers.

**Disadvantages.** Intermediate states are visible; some actions can't be undone (shipment already left → cancel rejected).

**Failure scenarios.** A failed compensation is never reported as COMPENSATED.

**At larger scale.** Reservation/TCC patterns, human workflows for non-reversible steps.
