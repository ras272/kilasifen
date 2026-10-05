"""Optional observability integrations for API and workers."""

from __future__ import annotations

import importlib
import logging
import re
from copy import deepcopy
from typing import Any

from kilasifen.config import Settings, get_settings
from kilasifen.logging import configure_logging, get_correlation_id

logger = logging.getLogger(__name__)

_SCRUBBED_VALUE = "[redacted]"
_SENSITIVE_FIELDS = {
    "api_key",
    "api_keys",
    "authorization",
    "certificate_password",
    "config",
    "configuration",
    "cookie",
    "generated_xml",
    "database_url",
    "encryption_key",
    "signed_xml",
    "sifen_request_xml",
    "sifen_response_raw",
    "last_query_request_xml",
    "last_query_response_raw",
    "payload_snapshot",
    "encrypted_p12",
    "encrypted_password",
    "password",
    "pfx",
    "pkcs12_data",
    "redis_url",
    "secret",
    "secrets",
    "sentry_dsn",
    "set_cookie",
    "settings",
    "token",
    "x_api_key",
    "csc",
    "csc_id",
}
_CERTIFICATE_MARKERS = ("BEGIN CERTIFICATE", "BEGIN PRIVATE KEY")
_BASE64_BLOB_PATTERN = re.compile(r"^[A-Za-z0-9+/=\s]{200,}$")
_INITIALIZED_COMPONENTS: set[str] = set()
_WORKER_LOGGING_CONFIGURED = False

#: Logger that RQ configures with its own text handlers when a worker starts.
_RQ_WORKER_LOGGER = "rq.worker"


def initialize_sentry(*, settings: Settings, component: str) -> bool:
    """Initialize Sentry only when the DSN and SDK are available."""

    if not settings.sentry_dsn:
        return False
    if component in _INITIALIZED_COMPONENTS:
        return True

    sentry_sdk = _import_optional("sentry_sdk")
    logging_module = _import_optional("sentry_sdk.integrations.logging")
    if sentry_sdk is None or logging_module is None:
        logger.warning(
            "observability.sentry_sdk_not_installed",
            extra={"component": component},
        )
        return False

    integrations = [
        logging_module.LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR,
        )
    ]
    if component == "api":
        fastapi_module = _import_optional("sentry_sdk.integrations.fastapi")
        if fastapi_module is not None:
            integrations.append(fastapi_module.FastApiIntegration())

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=integrations,
        send_default_pii=False,
        include_local_variables=False,
        before_send=_before_send,
        before_breadcrumb=_before_breadcrumb,
        before_send_transaction=_before_send_transaction,
    )
    sentry_sdk.set_tag("kila_component", component)
    _INITIALIZED_COMPONENTS.add(component)
    return True


def ensure_worker_observability() -> bool:
    """Initialize logging and Sentry for a worker or outbox process.

    Workers have no application factory: every job entry point and the outbox
    sweeper call this first. The first call in a process configures the same
    JSON logging as the API (``configure_logging``); later calls only make
    sure Sentry is initialized.
    """

    settings = get_settings()
    _configure_worker_logging(settings.log_level)
    return initialize_sentry(settings=settings, component="worker")


def _configure_worker_logging(level: str) -> None:
    global _WORKER_LOGGING_CONFIGURED
    if _WORKER_LOGGING_CONFIGURED:
        return
    configure_logging(level)
    rq_logger = logging.getLogger(_RQ_WORKER_LOGGER)
    if rq_logger.handlers:
        # RQ prints its own lifecycle lines; letting them also reach the root
        # JSON handler would log each of them twice.
        rq_logger.propagate = False
    _WORKER_LOGGING_CONFIGURED = True


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    del hint
    sanitized = _sanitize_payload(event)
    return _attach_correlation_id(sanitized)


def _before_breadcrumb(
    breadcrumb: dict[str, Any],
    hint: dict[str, Any],
) -> dict[str, Any] | None:
    del hint
    return _sanitize_payload(breadcrumb)


def _before_send_transaction(
    event: dict[str, Any],
    hint: dict[str, Any],
) -> dict[str, Any] | None:
    del hint
    sanitized = _sanitize_payload(event)
    return _attach_correlation_id(sanitized)


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(payload)
    return _sanitize_value(sanitized)


def _sanitize_value(value: Any, *, field_name: str | None = None):
    if field_name is not None and _is_sensitive_field(field_name):
        return _SCRUBBED_VALUE
    if isinstance(value, Settings):
        return _SCRUBBED_VALUE
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_name = str(key)
            sanitized[key_name] = _sanitize_value(item, field_name=key_name)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, field_name=field_name) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item, field_name=field_name) for item in value)
    if isinstance(value, str):
        if _should_redact_string(value):
            return _SCRUBBED_VALUE
        return value
    if isinstance(value, bytes):
        return _SCRUBBED_VALUE
    return value


def _is_sensitive_field(field_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", field_name.lower()).strip("_")
    if normalized in _SENSITIVE_FIELDS:
        return True
    return normalized.endswith(("_password", "_secret", "_token", "_api_key"))


def _should_redact_string(value: str) -> bool:
    if any(marker in value for marker in _CERTIFICATE_MARKERS):
        return True
    stripped = value.strip()
    if len(stripped) < 200:
        return False
    return bool(_BASE64_BLOB_PATTERN.fullmatch(stripped))


def _attach_correlation_id(event: dict[str, Any]) -> dict[str, Any]:
    correlation_id = get_correlation_id()
    if correlation_id is None:
        return event
    tags = event.setdefault("tags", {})
    tags.setdefault("correlation_id", correlation_id)
    return event


def _import_optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None
