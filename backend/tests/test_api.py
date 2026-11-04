"""API tests. Require fastapi + httpx (installed via requirements); skipped automatically otherwise."""
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def make(self, **env):
        from api.app import create_app
        from shared.broker import InMemoryBroker
        from shared.config import Settings
        from shared.db import Database
        d = tempfile.mkdtemp()
        s = Settings(env=env.get("env", "test"), enable_dev_endpoints=env.get("dev", True), admin_token=env.get("token", ""),
                     orchestrator_db=f"sqlite:///{d}/o.db", broker="memory")
        return TestClient(create_app(s, Database(s.orchestrator_db), InMemoryBroker()))

    body = {"customer_ref": "c1", "items": [{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 100}]}

    def test_validation_and_missing_resources(self):
        with self.make() as c:
            r = c.post("/api/v1/orders", json={"customer_ref": "", "items": []}, headers={"Idempotency-Key": "k" * 8})
            self.assertEqual(r.status_code, 422)
            self.assertEqual(c.get("/api/v1/orders/nope").status_code, 404)
            self.assertEqual(c.get("/api/v1/sagas/nope").status_code, 404)
            self.assertEqual(c.get("/api/v1/sagas?limit=1000").status_code, 422)

    def test_idempotent_create_and_pagination(self):
        with self.make() as c:
            h = {"Idempotency-Key": "idem-12345"}
            a, b = c.post("/api/v1/orders", json=self.body, headers=h), c.post("/api/v1/orders", json=self.body, headers=h)
            self.assertEqual((a.status_code, b.status_code, a.json()), (201, 200, b.json()))
            self.assertEqual(c.get("/api/v1/sagas?limit=1").json()["total"], 1)

    def test_invalid_state_transition_is_409(self):
        with self.make() as c:
            r = c.post("/api/v1/orders", json=self.body, headers={"Idempotency-Key": "idem-99999"}).json()
            self.assertEqual(c.post(f"/api/v1/sagas/{r['saga_id']}/retry").status_code, 409)

    def test_admin_and_dev_protection(self):
        with self.make(env="production", dev=True, token="s3cret") as c:  # dev endpoints invisible in production
            self.assertEqual(c.post("/api/v1/dev/failure-scenarios", json={"simulate": {}}).status_code, 404)
            r = c.post(
                "/api/v1/orders",
                json={**self.body, "simulate": {"payment_decline": True}},
                headers={"Idempotency-Key": "idem-77777"},
            ).json()
            self.assertEqual(c.post(f"/api/v1/sagas/{r['saga_id']}/recover").status_code, 401)
            self.assertEqual(
                c.post(f"/api/v1/sagas/{r['saga_id']}/recover", headers={"X-Admin-Token": "s3cret"}).status_code,
                409,
            )

    def test_health_ready_metrics(self):
        with self.make() as c:
            self.assertEqual(c.get("/api/v1/health").json()["status"], "ok")
            self.assertEqual(c.get("/api/v1/ready").status_code, 200)
            self.assertIn("sagaflow_http_requests_total", c.get("/metrics").text)


if __name__ == "__main__":
    unittest.main()
