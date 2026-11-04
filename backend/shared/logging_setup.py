"""Structured JSON logging with request / correlation / saga ids carried in contextvars."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("log_ctx", default={})
SENSITIVE = ("password", "token", "secret", "card")


def bind(**kw) -> None:
    ctx.set({**ctx.get(), **kw})


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        data = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                "service": self.service, "message": record.getMessage(), **ctx.get(),
                **{k: v for k, v in getattr(record, "extra_fields", {}).items()
                   if not any(s in k.lower() for s in SENSITIVE)}}
        if record.exc_info:
            data["error_classification"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(data, default=str)


def setup_logging(service: str, level: str = "INFO") -> logging.Logger:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    return logging.getLogger(service)


def log(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})
