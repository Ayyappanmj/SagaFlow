# API reference
Interactive docs: http://localhost:8000/docs (OpenAPI). All errors: `{"error":{"code","message","request_id"}}`. Every response carries `X-Request-ID` and `X-Correlation-ID`.

| Method & path | Notes |
|---|---|
| `POST /api/v1/orders` | Header `Idempotency-Key` (8–128 chars) required. 201 created, 200 replay of same key+body, 409 same key different body, 422 validation. Body: `customer_ref`, `items[{sku,quantity,unit_price_cents}]`, optional dev-only `simulate`. |
| `GET /api/v1/orders`, `/orders/{id}` | Paginated (`limit`≤100, `offset`); 404 if unknown. |
| `GET /api/v1/sagas?state=&q=&limit=&offset=` | `q` = exact saga or order id. |
| `GET /api/v1/sagas/{id}`, `/history` | Steps, attempts, errors; ordered event history. |
| `POST /api/v1/sagas/{id}/retry` | `REQUIRES_ATTENTION` only (else 409). Needs `X-Admin-Token` if `ADMIN_TOKEN` is set; with no token it is allowed only in dev mode. Body `{"clear_simulation":true}` (dev only). |
| `POST /api/v1/sagas/{id}/recover` | `RUNNING`/`COMPENSATING` only (else 409). Same auth. |
| `POST /api/v1/dev/failure-scenarios` | Arms a scenario for the next order(s); **404 unless `ENABLE_DEV_ENDPOINTS=true` and env is development/test**. |
| `GET /api/v1/stats`, `/dead-letters`, `/inventory`, `/payments`, `/shipments`, `/system-health` | Dashboard read models. |
| `GET /api/v1/health` / `/ready` / `/metrics` | Liveness / readiness (DB + broker) / Prometheus. |

Failure scenario keys (`simulate`): `inventory_reject`, `payment_decline`, `payment_timeout: N` (first N attempts time out), `shipping_fail`, `compensation_fail: ["payment_void"|"inventory_release"|"shipping_cancel"]`, `duplicate_delivery`, `drop_reply_once: ["inventory"|"payment"|"shipping"]`, `delay_ms`. Insufficient inventory is produced naturally with a large quantity.
