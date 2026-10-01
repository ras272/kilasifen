"""gEmis comes only from the registered emitter and its fiscal profile."""

from dataclasses import replace
from datetime import date, datetime, timezone
from xml.etree import ElementTree as ET

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.fiscal_profile import EconomicActivity
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.typed_xml_builder import (
    MT_TEST_EMITTER_NAME,
    build_typed_document_xml,
)
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile

_NS = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}


def test_document_cannot_be_built_without_a_fiscal_profile() -> None:
    with pytest.raises(SifenValidationError, match="emitters.fiscal_profile_required"):
        _build(emitter=replace(_emitter(), fiscal_profile=None))


def test_gemis_and_cdc_come_from_the_emitter_profile() -> None:
    profile = replace(
        fictional_fiscal_profile(),
        taxpayer_type=1,
        regime_type=8,
        trade_name="NOMBRE DE FANTASIA",
        activities=(
            EconomicActivity(code="62010", description="PROGRAMACION"),
            EconomicActivity(code="47190", description="VENTA AL POR MENOR"),
        ),
    )

    result = _build(emitter=replace(_emitter(), fiscal_profile=profile))

    emis = _gemis(result.generated_xml)
    assert _text(emis, "dRucEm") == "44444401"
    assert _text(emis, "dDVEmi") == "7"
    assert _text(emis, "iTipCont") == "1"
    assert _text(emis, "cTipReg") == "8"
    assert _text(emis, "dNomEmi") == "EMISOR FICTICIO SA"
    assert _text(emis, "dNomFanEmi") == "NOMBRE DE FANTASIA"
    assert _text(emis, "dDirEmi") == "CALLE FICTICIA"
    assert _text(emis, "dNumCas") == "123"
    assert _text(emis, "cDepEmi") == "1"
    assert _text(emis, "dDesDepEmi") == "CAPITAL"
    assert _text(emis, "dTelEmi") == "021123456"
    assert _text(emis, "dEmailE") == "facturacion@example.com"
    codes = [node.text for node in emis.findall("s:gActEco/s:cActEco", _NS)]
    assert codes == ["62010", "47190"]
    # CDC (MT v150 §10.1): RUC 3-10, DV 11 and iTipCont 25 from the same source.
    assert result.doc_id[2:10] == "44444401"
    assert result.doc_id[10] == "7"
    assert result.doc_id[24] == "1"


def test_establishment_override_replaces_the_default_address() -> None:
    profile = fictional_fiscal_profile()
    branch = replace(
        profile.address,
        street="SUCURSAL FICTICIA",
        district_code=7,
        district_description="DISTRITO FICTICIO",
        branch_name="SUCURSAL 2",
    )
    emitter = replace(
        _emitter(), fiscal_profile=replace(profile, establishments={"002": branch})
    )

    branch_emis = _gemis(_build(emitter=emitter, establecimiento="002").generated_xml)
    main_emis = _gemis(_build(emitter=emitter, establecimiento="001").generated_xml)

    assert _text(branch_emis, "dDirEmi") == "SUCURSAL FICTICIA"
    assert _text(branch_emis, "cDisEmi") == "7"
    assert _text(branch_emis, "dDesDisEmi") == "DISTRITO FICTICIO"
    assert _text(branch_emis, "dDenSuc") == "SUCURSAL 2"
    assert _text(main_emis, "dDirEmi") == "CALLE FICTICIA"
    assert main_emis.find("s:dDenSuc", _NS) is None


@pytest.mark.parametrize(
    ("payload_changes", "field"),
    [
        ({"emisor": {"ruc": "80069563"}}, "emisor.ruc"),
        ({"emisor": {"ruc": "44444401-8"}}, "emisor.ruc"),
        ({"emisor": {"dv": "8"}}, "emisor.dv"),
        ({"emisor": {"razon_social": "OTRA RAZON SOCIAL"}}, "emisor.razon_social"),
        ({"tipo_contribuyente": 1}, "tipo_contribuyente"),
    ],
)
def test_payload_cannot_change_the_emitter_identity(
    payload_changes: dict, field: str
) -> None:
    with pytest.raises(SifenValidationError, match=f"identity_mismatch:{field}"):
        _build(payload_changes=payload_changes)


def test_payload_may_repeat_the_emitter_identity_and_its_address_is_ignored() -> None:
    result = _build(
        payload_changes={
            "tipo_contribuyente": 2,
            "emisor": {
                "ruc": "44444401-7",
                "dv": "7",
                "razon_social": "emisor ficticio sa",
                "direccion": "DIRECCION DEL PAYLOAD",
                "telefono": "0981000000",
            },
        }
    )

    emis = _gemis(result.generated_xml)
    assert _text(emis, "dDirEmi") == "CALLE FICTICIA"
    assert _text(emis, "dTelEmi") == "021123456"


def test_test_environment_literal_replaces_the_legal_name_when_configured() -> None:
    result = _build(test_emitter_name_literal=MT_TEST_EMITTER_NAME)

    assert _text(_gemis(result.generated_xml), "dNomEmi") == MT_TEST_EMITTER_NAME


def test_test_literal_never_applies_to_production_emitters() -> None:
    emitter = replace(_emitter(), tax_environment="production")

    result = _build(emitter=emitter, test_emitter_name_literal=MT_TEST_EMITTER_NAME)

    assert _text(_gemis(result.generated_xml), "dNomEmi") == "EMISOR FICTICIO SA"


def test_production_emitter_named_with_the_test_literal_is_refused() -> None:
    # MT v150 validation 1263: the test literal is forbidden in production.
    emitter = replace(
        _emitter(), tax_environment="production", legal_name=MT_TEST_EMITTER_NAME
    )

    with pytest.raises(SifenValidationError, match="test_name_in_production"):
        _build(emitter=emitter)


def _build(
    *,
    emitter: Emitter | None = None,
    establecimiento: str = "001",
    payload_changes: dict | None = None,
    test_emitter_name_literal: str | None = None,
):
    payload = {
        "numero": 1,
        "establecimiento": establecimiento,
        "punto": "001",
        "fecha_emision": "2026-04-25T10:00:00",
        "codigo_seguridad": "482019375",
        "cliente": {
            "naturaleza": 1,
            "tipo_operacion": 1,
            "tipo_contribuyente": 2,
            "ruc": "80025298-5",
            "razon_social": "CLIENTE FICTICIO SA",
        },
        "items": [
            {
                "codigo_interno": "A-1",
                "descripcion": "Producto",
                "cantidad": "1",
                "precio_unitario": "110000",
                "afectacion": "gravado",
                "tasa": 10,
            }
        ],
        **(payload_changes or {}),
    }
    result = build_typed_document_xml(
        document=_document(payload),
        emitter=emitter or _emitter(),
        stamping=_stamping(),
        test_emitter_name_literal=test_emitter_name_literal,
    )
    assert result is not None
    return result


def _gemis(xml: str) -> ET.Element:
    emis = ET.fromstring(xml.encode("utf-8")).find("s:DE/s:gDatGralOpe/s:gEmis", _NS)
    assert emis is not None
    return emis


def _text(parent: ET.Element, tag: str) -> str | None:
    node = parent.find(f"s:{tag}", _NS)
    return None if node is None else node.text


def _document(payload: dict) -> Document:
    now = datetime.now(timezone.utc)
    return Document(
        id="doc-1",
        emitter_id="emitter-1",
        external_id=None,
        idempotency_key=None,
        document_type="factura",
        payload_snapshot={
            "typed_contract": {"contract": "factura_v1", "payload": payload}
        },
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
    )


def _emitter() -> Emitter:
    now = datetime.now(timezone.utc)
    return Emitter(
        id="emitter-1",
        external_id=None,
        ruc="44444401",
        dv="7",
        legal_name="EMISOR FICTICIO SA",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=now,
        updated_at=now,
        fiscal_profile=fictional_fiscal_profile(),
    )


def _stamping() -> Stamping:
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
