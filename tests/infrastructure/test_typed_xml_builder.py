from datetime import UTC, date, datetime

import pytest
from pysifen.sdk.errors import SifenValidationError

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.infrastructure.sifen.mapper import PysifenPayloadMapper


def test_mapper_builds_factura_xml_from_typed_payload() -> None:
    mapper = PysifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "factura_v1",
                "payload": {
                    "numero": 1001,
                    "fecha": "2026-04-25T10:00:00",
                    "cliente": {"ruc": "80069563-1", "razonSocial": "TIPS S.A"},
                    "items": [
                        {
                            "codigo": "A-001",
                            "descripcion": "Producto",
                            "cantidad": 1,
                            "precioUnitario": 100000,
                            "iva": 10,
                        }
                    ],
                },
            }
        }
    )

    emission_input = mapper.map_document(
        document,
        emitter=_build_emitter(),
        stamping=_build_stamping(),
    )

    assert emission_input.generated_xml is not None
    assert "<iTiDE>1</iTiDE>" in emission_input.generated_xml
    assert "<dNumDoc>0001001</dNumDoc>" in emission_input.generated_xml
    assert emission_input.doc_id is not None
    assert f'Id="{emission_input.doc_id}"' in emission_input.generated_xml


def test_mapper_builds_nota_credito_xml_from_typed_payload() -> None:
    mapper = PysifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "nota_credito_v1",
                "payload": {
                    "numero": 77,
                    "fecha": "2026-04-25T10:00:00",
                    "cliente": {"ruc": "80069563-1", "razonSocial": "TIPS S.A"},
                    "documento_asociado": {
                        "cdc": "01800123450001001000000012026010112345678901"
                    },
                    "items": [
                        {
                            "codigo": "NC-001",
                            "descripcion": "Devolucion",
                            "cantidad": 1,
                            "precioUnitario": 50000,
                            "iva": 10,
                        }
                    ],
                },
            }
        }
    )

    emission_input = mapper.map_document(
        document,
        emitter=_build_emitter(),
        stamping=_build_stamping(),
    )

    assert emission_input.generated_xml is not None
    assert "<iTiDE>5</iTiDE>" in emission_input.generated_xml
    assert "<dNumDoc>0000077</dNumDoc>" in emission_input.generated_xml
    assert "<gCamDEAsoc>" in emission_input.generated_xml
    assert "01800123450001001000000012026010112345678901" in emission_input.generated_xml
    assert emission_input.doc_id is not None


def test_mapper_rejects_typed_payload_without_required_fields() -> None:
    mapper = PysifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "factura_v1",
                "payload": {"numero": 1001},
            }
        }
    )

    with pytest.raises(SifenValidationError):
        mapper.map_document(
            document,
            emitter=_build_emitter(),
            stamping=_build_stamping(),
        )


def _build_document(*, payload_snapshot: dict) -> Document:
    return Document(
        id="doc-1",
        emitter_id="emitter-1",
        external_id="erp-doc-1",
        idempotency_key="idem-doc-1",
        document_type="factura",
        payload_snapshot=payload_snapshot,
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
        created_at=_now(),
        updated_at=_now(),
    )


def _build_emitter() -> Emitter:
    return Emitter(
        id="emitter-1",
        external_id="erp-ares",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=_now(),
        updated_at=_now(),
    )


def _build_stamping() -> Stamping:
    return Stamping(
        id="stamp-1",
        emitter_id="emitter-1",
        number="80024135",
        start_date=date(2024, 3, 11),
        end_date=None,
        is_active=True,
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )


def _now() -> datetime:
    return datetime.now(UTC)
