# ADR 0010: What the system cannot guarantee

**Context.** Honesty about guarantees.

**Options considered.** —

**Decision.** No cross-service isolation (intermediate states visible); no global ordering; no exactly-once delivery; no automatic resolution of unknown outcomes or failed compensations; mock payment/shipping only; test suite validated on SQLite + in-memory broker, not PostgreSQL/RabbitMQ in this repo's recorded run.

**Advantages.** Sets correct expectations for interviews and reviewers.

**Disadvantages.** —

**Failure scenarios.** See failure-recovery.md for the exact behaviours.

**At larger scale.** Production hardening: auth, HA broker/DB, observability alerts, runbooks.
