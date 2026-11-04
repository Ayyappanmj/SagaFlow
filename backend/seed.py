"""Development seed: python -m seed  (inserts demo stock into the inventory DB). Not run automatically."""
from inventory_service.service import InventoryService
from shared.config import Settings
from shared.db import Database
from shared.migrate import apply_migrations

STOCK = {"WIDGET": 50, "GADGET": 20, "GIZMO": 5, "DOOHICKEY": 100}

if __name__ == "__main__":
    db = Database(Settings().inventory_db)
    apply_migrations(db, "inventory")
    InventoryService(db).seed(STOCK)
    print("seeded inventory:", STOCK)
