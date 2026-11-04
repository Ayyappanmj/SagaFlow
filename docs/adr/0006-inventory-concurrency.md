# ADR 0006: Concurrent inventory reservations

**Context.** Two orders for 4 of 5 units must not both succeed.

**Options considered.** Read-modify-write in Python; `SELECT … FOR UPDATE`; conditional UPDATE; serializable isolation.

**Decision.** Conditional `UPDATE … WHERE available >= qty` plus `CHECK (available >= 0)`; multi-item orders use a savepoint and sorted SKUs.

**Advantages.** Atomic, no explicit locks in app code, no lost updates.

**Disadvantages.** Hot SKUs serialize on one row.

**Failure scenarios.** Partial multi-line reservations roll back with the savepoint.

**At larger scale.** Sharded counters or reservation queues for hot items.
