from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.mapper import KilaSifenPayloadMapper
from kilasifen.infrastructure.sifen.typed_xml_builder import _has_ds_namespace_prefix
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile


def test_mapper_builds_factura_xml_from_typed_payload() -> None:
    mapper = KilaSifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "factura_v1",
                "payload": {
                    "numero": 1001,
                    "fecha": "2026-04-25T10:00:00",
                    "cliente": {
                    "ruc": "80069563-1",
                    "razonSocial": "TIPS S.A",
                    "tipo_contribuyente": 2,
                },
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
    assert "<dTotOpeGs>" not in emission_input.generated_xml
    assert "<dTotalGs>" not in emission_input.generated_xml
    assert emission_input.doc_id is not None
    assert f'Id="{emission_input.doc_id}"' in emission_input.generated_xml


def test_mapper_builds_nota_credito_xml_from_typed_payload() -> None:
    mapper = KilaSifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "nota_credito_v1",
                "payload": {
                    "numero": 77,
                    "fecha": "2026-04-25T10:00:00",
                    "cliente": {
                    "ruc": "80069563-1",
                    "razonSocial": "TIPS S.A",
                    "tipo_contribuyente": 2,
                },
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
    assert "<iTipTra>" not in emission_input.generated_xml
    assert "<dDesTipTra>" not in emission_input.generated_xml
    assert "<gCamDEAsoc>" in emission_input.generated_xml
    associated_cdc = "01800123450001001000000012026010112345678901"
    assert associated_cdc in emission_input.generated_xml
    assert emission_input.doc_id is not None


def test_mapper_rejects_typed_payload_without_required_fields() -> None:
    mapper = KilaSifenPayloadMapper()
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


def test_mapper_rejects_receiver_address_without_house_number() -> None:
    mapper = KilaSifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "factura_v1",
                "payload": {
                    "numero": 1001,
                    "fecha": "2026-04-25T10:00:00",
                    "cliente": {
                        "naturaleza": 1,
                        "tipo_operacion": 1,
                        "tipo_contribuyente": 2,
                        "ruc": "80069563-1",
                        "razon_social": "TIPS S.A",
                        "direccion": "ASUNCION",
                    },
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

    with pytest.raises(
        SifenValidationError,
        match="documents.cliente.numero_casa_required",
    ):
        mapper.map_document(
            document,
            emitter=_build_emitter(),
            stamping=_build_stamping(),
        )


def test_mapper_accepts_ds_colon_inside_text_content() -> None:
    mapper = KilaSifenPayloadMapper()
    document = _build_document(
        payload_snapshot={
            "typed_contract": {
                "contract": "factura_v1",
                "payload": {
                    "numero": 1001,
                    "fecha": "2026-04-25T10:00:00",
                    "cliente": {
                    "ruc": "80069563-1",
                    "razonSocial": "TIPS S.A",
                    "tipo_contribuyente": 2,
                },
                    "items": [
                        {
                            "codigo": "A-001",
                            "descripcion": "Brands: zapatillas y cards: regalo",
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
    assert "Brands: zapatillas y cards: regalo" in emission_input.generated_xml


@pytest.mark.parametrize(
    "xml_text",
    [
        '<rDE><ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#"/></rDE>',
        "<rDE></ds:Signature></rDE>",
        '<rDE xmlns:ds="http://www.w3.org/2000/09/xmldsig#"/>',
    ],
)
def test_ds_prefix_detection_flags_real_markup(xml_text: str) -> None:
    assert _has_ds_namespace_prefix(xml_text)


def test_ds_prefix_detection_ignores_escaped_text() -> None:
    xml_text = "<rDE><dDesProSer>Brands: &lt;ds:x&gt; cards: 1</dDesProSer></rDE>"

    assert not _has_ds_namespace_prefix(xml_text)


def test_persisted_security_code_feeds_dcodseg_and_the_cdc() -> None:
    mapper = KilaSifenPayloadMapper()
    document = replace(
        _build_document(payload_snapshot=_minimal_factura_snapshot()),
        security_code="731640258",
    )

    emission_input = mapper.map_document(
        document, emitter=_build_emitter(), stamping=_build_stamping()
    )

    assert "<dCodSeg>731640258</dCodSeg>" in emission_input.generated_xml
    # MT v150 §10.1: dCodSeg occupies positions 35-43 of the CDC.
    assert emission_input.doc_id[34:43] == "731640258"


def test_rebuilding_the_same_document_yields_the_same_cdc() -> None:
    mapper = KilaSifenPayloadMapper()
    document = _build_document(payload_snapshot=_minimal_factura_snapshot())

    first = mapper.map_document(
        document, emitter=_build_emitter(), stamping=_build_stamping()
    )
    second = mapper.map_document(
        document, emitter=_build_emitter(), stamping=_build_stamping()
    )

    assert first.doc_id == second.doc_id


def test_document_without_security_code_is_refused_instead_of_a_constant() -> None:
    mapper = KilaSifenPayloadMapper()
    document = replace(
        _build_document(payload_snapshot=_minimal_factura_snapshot()),
        security_code=None,
    )

    with pytest.raises(SifenValidationError, match="codigo_seguridad.missing"):
        mapper.map_document(
            document, emitter=_build_emitter(), stamping=_build_stamping()
        )


def test_security_code_equal_to_the_document_number_is_refused() -> None:
    mapper = KilaSifenPayloadMapper()
    document = replace(
        _build_document(payload_snapshot=_minimal_factura_snapshot()),
        security_code="000001001",
    )

    with pytest.raises(SifenValidationError, match="equals_numero"):
        mapper.map_document(
            document, emitter=_build_emitter(), stamping=_build_stamping()
        )


def _minimal_factura_snapshot() -> dict:
    return {
        "typed_contract": {
            "contract": "factura_v1",
            "payload": {
                "numero": 1001,
                "fecha": "2026-04-25T10:00:00",
                "cliente": {
                    "ruc": "80069563-1",
                    "razonSocial": "TIPS S.A",
                    "tipo_contribuyente": 2,
                },
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
        security_code="482019375",
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
        fiscal_profile=fictional_fiscal_profile(),
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
    return datetime.now(timezone.utc)
