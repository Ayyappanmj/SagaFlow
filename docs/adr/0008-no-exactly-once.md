# ADR 0008: No exactly-once assumption

**Context.** Networks can't distinguish 'lost' from 'slow'.

**Options considered.** Claim exactly-once; at-least-once + idempotency.

**Decision.** At-least-once delivery everywhere, with idempotent effects ('effectively once').

**Advantages.** Honest and robust.

**Disadvantages.** Every handler must be written idempotently.

**Failure scenarios.** Duplicate/late/stale replies are ignored by state checks and message-id dedupe.

**At larger scale.** Broker-level transactions/streams where available; still need idempotency at the edges.
