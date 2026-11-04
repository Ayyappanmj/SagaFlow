"""Apply migrations to all service databases: python scripts/migrate.py  (services also do this at startup)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from shared.config import Settings  # noqa: E402
from shared.db import Database  # noqa: E402
from shared.migrate import apply_migrations  # noqa: E402

s = Settings()
for name, url in (("orchestrator", s.orchestrator_db), ("inventory", s.inventory_db), ("payment", s.payment_db), ("shipping", s.shipping_db)):
    print(name, apply_migrations(Database(url), name) or "up to date")
