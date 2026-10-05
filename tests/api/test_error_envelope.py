"""Framework errors share the documented error envelope."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url

API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="envelope") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        Base.metadata.create_all(build_engine(database_url))

        app = create_app()

        def explode() -> None:
            raise RuntimeError("internal detail that must not leak")

        app.add_api_route("/v1/test-only/explode", explode, methods=["GET"])
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client


def _assert_envelope(response, *, status: int, code: str, category: str) -> dict:
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["category"] == category
    assert error["message"]
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]
    return error


def test_unknown_route_returns_not_found_envelope(client: TestClient) -> None:
    response = client.get("/v1/does-not-exist", headers={"X-API-Key": API_KEY})

    _assert_envelope(
        response,
        status=404,
        code="request.route_not_found",
        category="not_found",
    )


def test_unsupported_method_returns_envelope_and_keeps_allow_header(
    client: TestClient,
) -> None:
    response = client.delete("/v1/health")

    _assert_envelope(
        response,
        status=405,
        code="request.method_not_allowed",
        category="invalid_request",
    )
    assert response.headers["Allow"] == "GET"


def test_request_validation_returns_field_details_without_echoing_input(
    client: TestClient,
) -> None:
    secret_csc = "S3CR3T" * 60
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "80024135",
            "dv": "5",
            "tax_environment": "staging",
            "csc": secret_csc,
        },
    )

    error = _assert_envelope(
        response,
        status=422,
        code="request.validation_failed",
        category="validation",
    )
    fields = {tuple(item["loc"]): item for item in error["details"]["errors"]}
    assert fields[("body", "legal_name")]["type"] == "missing"
    assert fields[("body", "tax_environment")]["type"] == "literal_error"
    assert fields[("body", "csc")]["type"] == "string_pattern_mismatch"
    assert all(set(item) == {"loc", "message", "type"} for item in fields.values())
    assert "S3CR3T" not in response.text


def test_malformed_json_returns_validation_envelope(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        content=b"{not-json",
    )

    error = _assert_envelope(
        response,
        status=422,
        code="request.validation_failed",
        category="validation",
    )
    assert error["details"]["errors"][0]["type"] == "json_invalid"


def test_unhandled_exception_returns_internal_envelope_with_correlation(
    client: TestClient,
) -> None:
    response = client.get("/v1/test-only/explode")

    _assert_envelope(
        response,
        status=500,
        code="server.internal_error",
        category="internal",
    )
    assert "internal detail" not in response.text
