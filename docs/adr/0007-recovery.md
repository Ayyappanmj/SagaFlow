# ADR 0007: Recovery of interrupted workflows

**Context.** Processes crash; messages and replies can be lost.

**Options considered.** In-memory timers; persisted state + periodic sweep.

**Decision.** State lives in PostgreSQL. `recover_stale` re-dispatches the in-flight step (same idempotency key) when a saga makes no progress and has no pending outbox row; runs at startup and periodically; operators can trigger `recover`/`retry`.

**Advantages.** Survives restarts without repeating external effects.

**Disadvantages.** Depends on idempotent services; staleness threshold is a trade-off (too low = redundant re-dispatches).

**Failure scenarios.** Unknown outcomes are shown as `UNKNOWN`/`REQUIRES_ATTENTION`, never guessed.

**At larger scale.** Durable timers in a workflow engine; leader election for sweepers.
