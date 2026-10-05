"""A fiscal rule broken by the payload is reported with a stable code."""

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
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile_payload
from kilasifen.testing.typed_documents import (
    FICTIONAL_EMITTER_DV,
    FICTIONAL_EMITTER_NAME,
    FICTIONAL_EMITTER_RUC,
    FICTIONAL_RECEIVER,
)

API_KEY = "secret-key"
_ITEM = {"descripcion": "Producto", "cantidad": 1, "precio_unitario": 1000}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="rules") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        Base.metadata.create_all(build_engine(database_url))
        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture
def emitter_id(client: TestClient) -> str:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": FICTIONAL_EMITTER_RUC,
            "dv": FICTIONAL_EMITTER_DV,
            "legal_name": FICTIONAL_EMITTER_NAME,
            "tax_environment": "test",
            "fiscal_profile": fictional_fiscal_profile_payload(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["emitter"]["id"]


def _factura_errors(client: TestClient, emitter_id: str, factura: dict) -> list[dict]:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={"factura": factura},
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "request.validation_failed"
    assert error["category"] == "validation"
    return error["details"]["errors"]


def test_receiver_rule_keeps_its_message_and_adds_the_code(
    client: TestClient, emitter_id: str
) -> None:
    cliente = dict(FICTIONAL_RECEIVER)
    del cliente["tipo_contribuyente"]

    errors = _factura_errors(client, emitter_id, {"cliente": cliente, "items": [_ITEM]})

    assert errors == [
        {
            "loc": ["body", "factura"],
            "message": "Value error, documents.cliente.tipo_contribuyente_required",
            "type": "value_error",
            "code": "documents.cliente.tipo_contribuyente_required",
        }
    ]


@pytest.mark.parametrize(
    ("changes", "loc", "code"),
    [
        (
            {"items": [{**_ITEM, "precio_unitario": 30}], "redondeo": "multiplo_50"},
            ["body", "factura"],
            "documents.redondeo.total_below_50",
        ),
        (
            {
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {
                            "tipo": "efectivo",
                            "monto": 1000,
                            "moneda": "PYG",
                            "tipo_cambio": 7300,
                        }
                    ],
                }
            },
            ["body", "factura", "condicion_operacion", "formas_pago", 0],
            "documents.condicion_operacion.formas_pago.tipo_cambio_not_allowed",
        ),
        (
            {
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {"tipo": "efectivo", "monto": 1000, "tipo_cambio": 7300}
                    ],
                }
            },
            ["body", "factura"],
            "documents.condicion_operacion.formas_pago.tipo_cambio_not_allowed",
        ),
        (
            {"items": [{**_ITEM, "afectacion": "exento", "tasa": 10}]},
            ["body", "factura", "items", 0],
            "documents.items.tasa_invalid",
        ),
        (
            {"moneda": "USD"},
            ["body", "factura"],
            "documents.currency.condicion_tipo_cambio_required",
        ),
        (
            {"codigo_seguridad": "0"},
            ["body", "factura", "codigo_seguridad"],
            "documents.codigo_seguridad.zero",
        ),
    ],
    ids=[
        "totals",
        "payment-1557-in-pyg",
        "payment-1557-in-the-operation-currency",
        "item-rate",
        "currency",
        "security-code",
    ],
)
def test_fiscal_rules_report_their_code_at_the_failing_location(
    client: TestClient, emitter_id: str, changes: dict, loc: list, code: str
) -> None:
    factura = {"cliente": dict(FICTIONAL_RECEIVER), "items": [_ITEM], **changes}

    errors = _factura_errors(client, emitter_id, factura)

    assert [(entry["loc"], entry.get("code")) for entry in errors] == [(loc, code)]
    assert errors[0]["type"] == "value_error"


def test_contract_errors_without_a_fiscal_rule_have_no_code(
    client: TestClient, emitter_id: str
) -> None:
    errors = _factura_errors(client, emitter_id, {"cliente": dict(FICTIONAL_RECEIVER)})

    assert errors == [
        {
            "loc": ["body", "factura", "items"],
            "message": "Field required",
            "type": "missing",
        }
    ]
