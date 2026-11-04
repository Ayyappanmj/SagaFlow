"""Load test against the running Docker stack:  locust -f benchmarks/locustfile.py --host http://localhost:8000
Headless example: locust -f benchmarks/locustfile.py --host http://localhost:8000 -u 20 -r 5 -t 60s --headless --csv benchmarks/results/run
(Seed enough stock first: the default seed has 50 WIDGET; orders beyond that FAIL with INSUFFICIENT_STOCK, which is a valid outcome.)"""
import uuid

from locust import HttpUser, between, task


class Shopper(HttpUser):
    wait_time = between(0.05, 0.3)

    @task(5)
    def place_order(self):
        self.client.post("/api/v1/orders", name="POST /orders", headers={"Idempotency-Key": str(uuid.uuid4())},
                         json={"customer_ref": "load", "items": [{"sku": "DOOHICKEY", "quantity": 1, "unit_price_cents": 500}]})

    @task(2)
    def list_sagas(self):
        self.client.get("/api/v1/sagas?limit=20", name="GET /sagas")
