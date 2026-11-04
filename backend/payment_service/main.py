from shared.app_factory import service_app
from shared.config import Settings
from shared.db import Database

from .service import PaymentService

settings = Settings()
svc = PaymentService(Database(settings.payment_db), limit_cents=settings.payment_limit_cents)


def routes(app, s):
    @app.get("/api/v1/payments")
    def payments():
        return {"items": s.list_payments()}


app = service_app("payment", svc, settings, routes)
