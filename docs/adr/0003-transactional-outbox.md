# ADR 0003: Transactional outbox

**Context.** Writing the DB and publishing to the broker can't be one atomic action (dual-write problem).

**Options considered.** Publish then write; write then publish; two-phase commit; outbox.

**Decision.** Write the event to `outbox_events` in the same local transaction as the state change; a relay publishes later.

**Advantages.** No lost events when a process crashes between DB commit and publish.

**Disadvantages.** Extra table and relay latency; duplicates are possible; ordering is only per-relay-batch best effort.

**Failure scenarios.** Crash between publish and marking published → re-publish (handled by idempotent consumers).

**At larger scale.** CDC (Debezium) tailing the WAL; `SKIP LOCKED` multi-relay.
