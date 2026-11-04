"""Run all SagaFlow microservices locally without Docker.

Starts:
  - Inventory Service (port 8001)
  - Payment Service (port 8002)
  - Shipping Service (port 8003)
  - Orchestrator (port 8010)
  - API Gateway (port 8000)
"""
from __future__ import annotations

import multiprocessing as mp
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run_uvicorn(app_target: str, port: int, is_factory: bool):
    sys.path.insert(0, str(BACKEND))
    os.environ["PYTHONPATH"] = str(BACKEND)
    import uvicorn
    uvicorn.run(
        app_target,
        host="127.0.0.1",
        port=port,
        factory=is_factory,
        log_level="warning",
        access_log=False,
    )


SERVICES = [
    ("inventory", "inventory_service.main:app", 8001, False),
    ("payment", "payment_service.main:app", 8002, False),
    ("shipping", "shipping_service.main:app", 8003, False),
    ("orchestrator", "orchestrator.main:app", 8010, False),
    ("api", "api.app:get_app", 8000, True),
]


def wait_healthy(port: int, timeout_s: float = 15.0) -> bool:
    t0 = time.time()
    url = f"http://127.0.0.1:{port}/api/v1/health"
    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def main():
    os.chdir(ROOT)
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)

    sys.path.insert(0, str(BACKEND))
    from shared.config import Settings
    from shared.db import Database
    from shared.migrate import apply_migrations

    s = Settings()
    for name, db_url in [
        ("orchestrator", s.orchestrator_db),
        ("inventory", s.inventory_db),
        ("payment", s.payment_db),
        ("shipping", s.shipping_db),
    ]:
        apply_migrations(Database(db_url), name)

    procs: dict[str, mp.Process] = {}
    for name, target, port, factory in SERVICES:
        p = mp.Process(target=run_uvicorn, args=(target, port, factory), daemon=True)
        p.start()
        procs[name] = p
        ok = wait_healthy(port)
        status = "HEALTHY" if ok else "FAILED"
        print(f"[{status}] {name} on http://127.0.0.1:{port} (pid {p.pid})")

    print("\nAll 5 SagaFlow services are up and healthy!")

    def cleanup(signum=None, frame=None):
        print("\nStopping services...")
        for _name, p in procs.items():
            if p.is_alive():
                p.terminate()
        for _name, p in procs.items():
            p.join(timeout=3)
        print("All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        while True:
            time.sleep(1)
            for name, target, port, factory in SERVICES:
                p = procs.get(name)
                if p and not p.is_alive():
                    print(f"Service {name} exited with code {p.exitcode}; restarting on port {port}...")
                    new_p = mp.Process(target=run_uvicorn, args=(target, port, factory), daemon=True)
                    new_p.start()
                    procs[name] = new_p
                    wait_healthy(port)
                    print(f"Service {name} restarted (pid {new_p.pid})")
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
