"""Run all SagaFlow microservices locally without Docker.

Starts:
  - Inventory Service (port 8001)
  - Payment Service (port 8002)
  - Shipping Service (port 8003)
  - Orchestrator (port 8010)
  - API Gateway (port 8000)

Monitors their health and cleans up on exit.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

SERVICES = [
    ("inventory", "inventory_service.main:app", 8001, None),
    ("payment", "payment_service.main:app", 8002, None),
    ("shipping", "shipping_service.main:app", 8003, None),
    ("orchestrator", "orchestrator.main:app", 8010, None),
    ("api", "api.app:get_app", 8000, ["--factory"]),
]


def wait_healthy(port: int, name: str, timeout_s: float = 15.0) -> bool:
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

    # Ensure migrations are applied first
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

    logs_dir = data_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    procs: dict[str, subprocess.Popen] = {}
    py = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND)

    def spawn(name, app_target, port, extra_args):
        cmd = [py, "-m", "uvicorn", app_target, "--host", "127.0.0.1", "--port", str(port)]
        if extra_args:
            cmd.extend(extra_args)
        log_f = open(logs_dir / f"{name}.log", "a", encoding="utf-8")
        return subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=log_f, stderr=subprocess.STDOUT)

    for name, app_target, port, extra_args in SERVICES:
        p = spawn(name, app_target, port, extra_args)
        procs[name] = p
        ok = wait_healthy(port, name)
        status = "HEALTHY" if ok else "FAILED"
        print(f"[{status}] {name} on http://127.0.0.1:{port}")

    print("\nAll services started! Press Ctrl+C to stop.")

    def cleanup(signum=None, frame=None):
        print("\nStopping services...")
        for _name, p in procs.items():
            p.terminate()
        for _name, p in procs.items():
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
        print("All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    svc_map = {name: (app_target, port, extra_args) for name, app_target, port, extra_args in SERVICES}

    try:
        while True:
            time.sleep(1)
            for name, p in list(procs.items()):
                if p.poll() is not None:
                    print(f"Service {name} exited with code {p.returncode}; reading log:")
                    log_path = logs_dir / f"{name}.log"
                    if log_path.exists():
                        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
                        print("\n".join(lines))
                    app_target, port, extra_args = svc_map[name]
                    print(f"Restarting {name}...")
                    new_p = spawn(name, app_target, port, extra_args)
                    procs[name] = new_p
                    wait_healthy(port, name)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
