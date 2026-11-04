# ADR 0004: Idempotent consumers

**Context.** At-least-once delivery means duplicates.

**Options considered.** Hope for exactly-once; dedupe in memory; dedupe in the DB.

**Decision.** `processed_messages(message_id, consumer)` + unique business keys, inside the same transaction as the effect; duplicates re-emit the stored reply.

**Advantages.** Correct under redelivery and crashes; survives restarts.

**Disadvantages.** Extra writes per message; table grows (needs pruning).

**Failure scenarios.** Dedupe row and effect commit together, so neither can exist without the other.

**At larger scale.** TTL-based cleanup of processed ids; idempotency keys honoured by external providers.
