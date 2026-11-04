"""Smoke test against the running stack: places a happy-path and a shipping-failure order, prints final states."""
import json
import time
import urllib.request
import uuid

BASE = "http://localhost:8000/api/v1"


def call(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


for label, sim in (("happy path", None), ("shipping failure -> compensation", {"shipping_fail": True})):
    o = call("POST", "/orders", {"customer_ref": "smoke", "simulate": sim,
                                 "items": [{"sku": "WIDGET", "quantity": 1, "unit_price_cents": 1000}]},
             {"Idempotency-Key": str(uuid.uuid4())})
    for _ in range(60):
        s = call("GET", f"/sagas/{o['saga_id']}")
        if s["state"] not in ("RUNNING", "COMPENSATING", "PENDING"):
            break
        time.sleep(0.5)
    print(f"{label}: saga {o['saga_id']} -> {s['state']}")
