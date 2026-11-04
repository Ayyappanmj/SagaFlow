# ADR 0001: Saga orchestration instead of choreography

**Context.** Order workflows need a clear, inspectable sequence with compensation.

**Options considered.** Choreography (services react to each other's events); orchestration (a central coordinator sends commands).

**Decision.** Orchestration: one `SagaEngine` owns the state machine and history.

**Advantages.** Workflow logic in one place; easy to inspect, retry and recover; simple dashboard.

**Disadvantages.** The orchestrator is a central component and coupling point; must be made highly available.

**Failure scenarios.** If the orchestrator is down, no saga progresses (state is safe in the DB and resumes on restart).

**At larger scale.** Choreography or workflow engines (Temporal, Camunda) when many teams own many workflows.
