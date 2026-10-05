"""Logging helpers for the Kila SIFEN platform."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone

_correlation_id_ctx: ContextVar[str | None] = ContextVar(
    "kila_sifen_correlation_id",
    default=None,
)

_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
}


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = get_correlation_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = _normalize_log_value(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_logging(level: str) -> None:
    """Configure application logging once per process."""

    root_logger = logging.getLogger()
    normalized_level = getattr(logging, level.upper(), logging.INFO)
    formatter = JsonLogFormatter()

    root_logger.setLevel(normalized_level)
    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.setLevel(normalized_level)
            handler.setFormatter(formatter)
        return

    handler = logging.StreamHandler()
    handler.setLevel(normalized_level)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


def set_correlation_id(value: str | None) -> Token:
    """Bind a correlation id to the current execution context."""

    return _correlation_id_ctx.set(value)


def reset_correlation_id(token: Token) -> None:
    """Reset the correlation id for the current execution context."""

    _correlation_id_ctx.reset(token)


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current execution context."""

    return _correlation_id_ctx.get()


def _normalize_log_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _normalize_log_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_log_value(item) for item in value]
    return str(value)
