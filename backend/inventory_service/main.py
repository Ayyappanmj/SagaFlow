from shared.app_factory import service_app
from shared.config import Settings
from shared.db import Database

from .service import InventoryService

settings = Settings()
svc = InventoryService(Database(settings.inventory_db))


def routes(app, s):
    @app.get("/api/v1/inventory")
    def stock():
        return {"items": s.list_stock()}

    @app.get("/api/v1/reservations")
    def reservations():
        return {"items": s.list_reservations()}


app = service_app("inventory", svc, settings, routes)
