"""Environment-based configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _b(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("SAGAFLOW_ENV", "development"))
    orchestrator_db: str = field(default_factory=lambda: os.getenv("ORCHESTRATOR_DB_URL", "sqlite:///./data/orchestrator.db"))
    inventory_db: str = field(default_factory=lambda: os.getenv("INVENTORY_DB_URL", "sqlite:///./data/inventory.db"))
    payment_db: str = field(default_factory=lambda: os.getenv("PAYMENT_DB_URL", "sqlite:///./data/payment.db"))
    shipping_db: str = field(default_factory=lambda: os.getenv("SHIPPING_DB_URL", "sqlite:///./data/shipping.db"))
    rabbitmq_url: str = field(default_factory=lambda: os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"))
    broker_db: str = field(default_factory=lambda: os.getenv("BROKER_DB_URL", "sqlite:///./data/broker.db"))
    broker: str = field(default_factory=lambda: os.getenv("BROKER", "rabbitmq"))  # rabbitmq | memory | sqlite
    max_attempts: int = field(default_factory=lambda: int(os.getenv("RETRY_MAX_ATTEMPTS", "3")))
    retry_base_delay_s: float = field(default_factory=lambda: float(os.getenv("RETRY_BASE_DELAY_S", "1")))
    stale_after_s: float = field(default_factory=lambda: float(os.getenv("STALE_AFTER_S", "60")))
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", ""))
    enable_dev_endpoints: bool = field(default_factory=lambda: _b("ENABLE_DEV_ENDPOINTS"))
    payment_limit_cents: int = field(default_factory=lambda: int(os.getenv("PAYMENT_LIMIT_CENTS", "100000")))
    inventory_url: str = field(default_factory=lambda: os.getenv("INVENTORY_URL", "http://127.0.0.1:8001"))
    payment_url: str = field(default_factory=lambda: os.getenv("PAYMENT_URL", "http://127.0.0.1:8002"))
    orchestrator_url: str = field(default_factory=lambda: os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8010"))
    shipping_url: str = field(default_factory=lambda: os.getenv("SHIPPING_URL", "http://127.0.0.1:8003"))

    @property
    def dev_mode(self) -> bool:
        """Failure injection is only honoured when explicitly enabled AND env is development/test."""
        return self.enable_dev_endpoints and self.env in ("development", "test")
