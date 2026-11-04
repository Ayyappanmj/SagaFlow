# ADR 0002: RabbitMQ for commands and events

**Context.** Services must keep working when peers are temporarily unavailable.

**Options considered.** Direct HTTP calls; Kafka; RabbitMQ.

**Decision.** RabbitMQ with durable queues, persistent messages, explicit acks, per-queue retry (TTL) and dead-letter queues.

**Advantages.** Mature, simple to run locally, great management UI, per-message acks and DLQs.

**Disadvantages.** Not a log: no replay of history; poll-based consumption here trades throughput for simplicity.

**Failure scenarios.** Broker outage: outbox rows wait; consumers reconnect with backoff.

**At larger scale.** Kafka for very high throughput / replay; push consumers (`basic_consume`) with prefetch.
