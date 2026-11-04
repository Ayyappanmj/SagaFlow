# ADR 0009: Service boundaries and data ownership

**Context.** The orchestrator must not edit business tables.

**Options considered.** Shared DB; schema per service; DB per service.

**Decision.** Separate PostgreSQL database per service; only the owning service changes its tables; communication via messages (commands/replies) and read-only HTTP queries. Orders are co-located with the orchestrator DB for simplicity.

**Advantages.** Clear ownership, independent evolution.

**Disadvantages.** No cross-service joins; more connections; dashboard needs HTTP fan-out.

**Failure scenarios.** One service down affects only its pages/steps.

**At larger scale.** Separate Order service; API composition/CQRS read model.
