# Failure recovery

| Failure | What happens | Where it is tested |
|---|---|---|
| Process dies before outbox relay ran | Outbox rows are in the DB; the new relay publishes them | `test_restart_with_unpublished_outbox_loses_nothing` |
| Broker down | Publish fails; row stays `PENDING`, `available_at` pushed out with backoff | `test_broker_down_keeps_events_pending…` |
| Relay publishes, dies before marking published | Event is published again (at-least-once); consumers dedupe | `test_crash_between_publish_and_mark…` |
| Consumer dies after DB commit, before ack | Broker redelivers; `processed_messages` makes it a no-op that re-emits the stored reply | `test_worker_killed_after_commit_before_ack…` |
| Service committed but its reply was lost | Saga looks stuck; stale-saga recovery re-dispatches the *same idempotency key*; the service replays its stored result — no second effect | `test_lost_reply_is_recovered_without_repeating_effects` |
| Broker lost messages / orchestrator restart mid-saga | Startup recovery (`recover_stale`) re-dispatches in-flight steps | `test_restart_mid_saga_resumes_via_startup_recovery` |
| Poison message | Schema errors → DLQ immediately; handler errors → bounded retries → DLQ | `ConsumerTests` |
| Compensation fails | Saga → `REQUIRES_ATTENTION`, never `COMPENSATED`; remaining compensations stay `PENDING`; operator `retry` resumes | `test_compensation_failure_is_never_marked_compensated…` |
| Outcome unknown (timeouts exhausted) | Step `UNKNOWN`, saga `REQUIRES_ATTENTION`; `retry` re-dispatches safely (idempotent) | `test_exhausted_retries_represent_unknown_outcome…` |
| Concurrent writers on one saga | Optimistic `version` check; loser's message is retried and sees fresh state | `test_optimistic_concurrency_rejects_stale_writer` |

**Why re-dispatch is safe:** every command carries `idempotency_key = saga:step:action`; each service keeps one row per (saga) effect under a UNIQUE constraint and a stored result per `message_id`.

**Recovery limitations:** a saga whose command is still waiting in the outbox is deliberately *not* re-dispatched (the relay owns it). Recovery relies on services being idempotent — a real external payment provider would need to support idempotency keys too. If a service is permanently down, sagas wait; there is no automatic timeout-to-compensation for forward steps beyond the retry budget. Multiple relay instances may publish the same row twice (safe, but wasteful; `FOR UPDATE SKIP LOCKED` would be the production improvement).
