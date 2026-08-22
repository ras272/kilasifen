import logging
import sys
from types import ModuleType

from kilasifen.api.app import create_app
from kilasifen.config import Settings, get_settings
from kilasifen.logging import reset_correlation_id, set_correlation_id
from kilasifen.observability import (
    _INITIALIZED_COMPONENTS,
    _before_breadcrumb,
    _before_send,
    ensure_worker_observability,
    initialize_sentry,
)


def test_before_send_redacts_sensitive_fields_and_attaches_correlation_id() -> None:
    token = set_correlation_id("corr-sentry-1")
    try:
        event = {
            "extra": {
                "generated_xml": "<rDE><Signature>secret</Signature></rDE>",
                "payload_snapshot": {"foo": "bar"},
            },
            "contexts": {
                "job": {
                    "encrypted_password": "super-secret",
                    "safe": "ok",
                }
            },
            "breadcrumbs": {
                "values": [
                    {
                        "data": {
                            "signed_xml": "<signed/>",
                            "other": "kept",
                        }
                    }
                ]
            },
            "exception": {
                "values": [
                    {"value": "BEGIN CERTIFICATE-----secret-----"},
                    {"value": "A" * 220},
                ]
            },
        }

        sanitized = _before_send(event, {})

        assert sanitized is not None
        assert sanitized["extra"]["generated_xml"] == "[redacted]"
        assert sanitized["extra"]["payload_snapshot"] == "[redacted]"
        assert sanitized["contexts"]["job"]["encrypted_password"] == "[redacted]"
        assert (
            sanitized["breadcrumbs"]["values"][0]["data"]["signed_xml"]
            == "[redacted]"
        )
        assert sanitized["exception"]["values"][0]["value"] == "[redacted]"
        assert sanitized["exception"]["values"][1]["value"] == "[redacted]"
        assert sanitized["tags"]["correlation_id"] == "corr-sentry-1"
    finally:
        reset_correlation_id(token)


def test_before_breadcrumb_redacts_sensitive_fields() -> None:
    breadcrumb = {
        "message": "webhook failed",
        "data": {
            "csc": "ABCD0000000000000000000000000000",
            "delivery_id": "delivery-1",
        },
    }

    sanitized = _before_breadcrumb(breadcrumb, {})

    assert sanitized is not None
    assert sanitized["data"]["csc"] == "[redacted]"
    assert sanitized["data"]["delivery_id"] == "delivery-1"


def test_initialize_sentry_returns_false_without_dsn() -> None:
    _INITIALIZED_COMPONENTS.clear()

    initialized = initialize_sentry(
        settings=Settings(database_url="sqlite:///./kilasifen.db"),
        component="api",
    )

    assert initialized is False


def test_initialize_sentry_configures_optional_sdk(monkeypatch) -> None:
    _INITIALIZED_COMPONENTS.clear()
    captured = _install_fake_sentry(monkeypatch)
    settings = Settings(
        database_url="sqlite:///./kilasifen.db",
        sentry_dsn="https://public@example.ingest.sentry.io/1",
    )

    initialized = initialize_sentry(settings=settings, component="api")

    assert initialized is True
    assert captured["init_kwargs"]["dsn"] == settings.sentry_dsn
    assert captured["init_kwargs"]["environment"] == "development"
    assert captured["init_kwargs"]["traces_sample_rate"] == 0.0
    assert captured["init_kwargs"]["send_default_pii"] is False
    assert captured["init_kwargs"]["include_local_variables"] is False
    integrations = captured["init_kwargs"]["integrations"]
    assert len(integrations) == 2
    assert integrations[0].level == logging.INFO
    assert integrations[0].event_level == logging.ERROR
    assert integrations[1].name == "fastapi"
    assert captured["tags"] == [("kila_component", "api")]


def test_before_send_redacts_composite_settings_and_header_secrets() -> None:
    event = {
        "extra": {
            "settings": Settings(
                api_keys=["kila_live_secret"],
                encryption_key="not-a-real-fernet-key",
                database_url="postgresql://user:password@db.internal/kila",
                _env_file=None,
            ),
            "headers": {
                "X-API-Key": "kila_live_secret",
                "authorization": "Bearer private-token",
                "accept": "application/json",
            },
            "certificate_bytes": b"binary-private-material",
        }
    }

    sanitized = _before_send(event, {})

    assert sanitized is not None
    assert sanitized["extra"]["settings"] == "[redacted]"
    assert sanitized["extra"]["headers"]["X-API-Key"] == "[redacted]"
    assert sanitized["extra"]["headers"]["authorization"] == "[redacted]"
    assert sanitized["extra"]["headers"]["accept"] == "application/json"
    assert sanitized["extra"]["certificate_bytes"] == "[redacted]"


def test_create_app_initializes_api_sentry(monkeypatch) -> None:
    captured = {}
    settings = Settings(database_url="sqlite:///./kilasifen.db")
    monkeypatch.setattr("kilasifen.api.app.get_settings", lambda: settings)
    monkeypatch.setattr(
        "kilasifen.api.app.initialize_sentry",
        lambda *, settings, component: captured.update(
            {"settings": settings, "component": component}
        ),
    )

    create_app()

    assert captured["settings"] is settings
    assert captured["component"] == "api"


def test_ensure_worker_observability_uses_worker_component(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(
        "kilasifen.observability.get_settings",
        lambda: Settings(
            database_url="sqlite:///./kilasifen.db",
            sentry_dsn="https://public@example.ingest.sentry.io/1",
            sentry_environment="production",
        ),
    )
    captured = {}
    monkeypatch.setattr(
        "kilasifen.observability.initialize_sentry",
        lambda *, settings, component: captured.update(
            {"settings": settings, "component": component}
        )
        or True,
    )

    initialized = ensure_worker_observability()

    assert initialized is True
    assert captured["component"] == "worker"
    assert captured["settings"].sentry_environment == "production"


def _install_fake_sentry(monkeypatch) -> dict:
    captured: dict = {"tags": []}

    class FakeLoggingIntegration:
        def __init__(self, *, level, event_level):
            self.level = level
            self.event_level = event_level

    class FakeFastApiIntegration:
        def __init__(self):
            self.name = "fastapi"

    sentry_sdk = ModuleType("sentry_sdk")

    def fake_init(**kwargs):
        captured["init_kwargs"] = kwargs

    def fake_set_tag(key, value):
        captured["tags"].append((key, value))

    sentry_sdk.init = fake_init
    sentry_sdk.set_tag = fake_set_tag

    logging_module = ModuleType("sentry_sdk.integrations.logging")
    logging_module.LoggingIntegration = FakeLoggingIntegration

    fastapi_module = ModuleType("sentry_sdk.integrations.fastapi")
    fastapi_module.FastApiIntegration = FakeFastApiIntegration

    monkeypatch.setitem(sys.modules, "sentry_sdk", sentry_sdk)
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.logging",
        logging_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.fastapi",
        fastapi_module,
    )
    return captured
