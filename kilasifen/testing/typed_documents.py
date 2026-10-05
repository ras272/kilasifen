"""Fictional emitter, stamping and typed documents for builder tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile

#: MT v150 p. 211 example RUC; its DV is 7 (modulo 11).
FICTIONAL_EMITTER_RUC = "44444401"
FICTIONAL_EMITTER_DV = "7"
FICTIONAL_EMITTER_NAME = "EMISOR FICTICIO SA"
#: Receiver RUC of the DNIT Guia de Mejores Practicas example (DV 5).
FICTIONAL_RECEIVER = {
    "naturaleza": 1,
    "tipo_operacion": 1,
    "tipo_contribuyente": 2,
    "ruc": "80025298-5",
    "razon_social": "CLIENTE FICTICIO SA",
}


def fictional_emitter(**changes) -> Emitter:
    """Return an active test-environment emitter with a complete profile."""

    now = datetime.now(timezone.utc)
    values = {
        "id": "emitter-1",
        "external_id": None,
        "ruc": FICTIONAL_EMITTER_RUC,
        "dv": FICTIONAL_EMITTER_DV,
        "legal_name": FICTIONAL_EMITTER_NAME,
        "tax_environment": "test",
        "status": "active",
        "csc": "ABCD0000000000000000000000000000",
        "csc_id": "0001",
        "created_at": now,
        "updated_at": now,
        "fiscal_profile": fictional_fiscal_profile(),
    }
    values.update(changes)
    return Emitter(**values)


def fictional_stamping() -> Stamping:
    """Return an active stamping that started before every test date."""

    now = datetime.now(timezone.utc)
    return Stamping(
        id="stamp-1",
        emitter_id="emitter-1",
        number="12345678",
        start_date=date(2024, 3, 11),
        end_date=None,
        is_active=True,
        status="active",
        created_at=now,
        updated_at=now,
    )


def typed_document(
    payload: dict,
    *,
    contract: str = "factura_v1",
    security_code: str | None = "364052981",
) -> Document:
    """Return a queued document carrying ``payload`` as a typed contract."""

    now = datetime.now(timezone.utc)
    return Document(
        id="doc-1",
        emitter_id="emitter-1",
        external_id=None,
        idempotency_key=None,
        document_type="factura",
        payload_snapshot={"typed_contract": {"contract": contract, "payload": payload}},
        generated_xml=None,
        signed_xml=None,
        sifen_request_xml=None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=None,
        internal_status="queued",
        sifen_status=None,
        sifen_result_code=None,
        sifen_result_message=None,
        created_at=now,
        updated_at=now,
        security_code=security_code,
    )


def factura_payload(**changes) -> dict:
    """Return a minimal valid factura payload (one 110.000 Gs item)."""

    payload = {
        "numero": 7,
        "establecimiento": "001",
        "punto": "001",
        "fecha_emision": "2026-04-25T10:00:00",
        "cliente": dict(FICTIONAL_RECEIVER),
        "items": [
            {
                "descripcion": "Producto",
                "cantidad": "1",
                "precio_unitario": "110000",
                "afectacion": "gravado",
                "tasa": 10,
            }
        ],
    }
    payload.update(changes)
    return payload
