from shared.app_factory import service_app
from shared.config import Settings
from shared.db import Database

from .service import ShippingService

settings = Settings()
svc = ShippingService(Database(settings.shipping_db))


def routes(app, s):
    @app.get("/api/v1/shipments")
    def shipments():
        return {"items": s.list_shipments()}


app = service_app("shipping", svc, settings, routes)
