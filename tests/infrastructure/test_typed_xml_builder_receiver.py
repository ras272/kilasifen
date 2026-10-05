"""gDatRec and gRespDE as the builder writes them (F30-F34)."""

from xml.etree import ElementTree as ET

import pytest

from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.typed_xml_builder import build_typed_document_xml
from kilasifen.testing.typed_documents import (
    factura_payload,
    fictional_emitter,
    fictional_stamping,
    typed_document,
)

_NS = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}
_INNOMINADO = {"naturaleza": 2, "tipo_operacion": 2, "tipo_documento_identidad": 5}


def _build(payload: dict, *, contract: str = "factura_v1") -> ET.Element:
    result = build_typed_document_xml(
        document=typed_document(payload, contract=contract),
        emitter=fictional_emitter(),
        stamping=fictional_stamping(),
    )
    assert result is not None
    return ET.fromstring(result.generated_xml.encode("utf-8"))


def _receiver(root: ET.Element) -> dict[str, str]:
    rec = root.find("s:DE/s:gDatGralOpe/s:gDatRec", _NS)
    assert rec is not None
    return {child.tag.split("}")[1]: child.text for child in rec}


def test_innominado_receiver_is_written_with_zero_and_sin_nombre() -> None:
    root = _build(factura_payload(cliente=dict(_INNOMINADO)))

    receiver = _receiver(root)
    assert receiver["iTipIDRec"] == "5"
    assert receiver["dDTipIDRec"] == "Innominado"
    assert receiver["dNumIDRec"] == "0"
    assert receiver["dNomRec"] == "Sin Nombre"
    assert "dDirRec" not in receiver


def test_innominado_from_seven_million_guaranies_is_refused() -> None:
    # 1321 (NT 24): F014 >= 7.000.000 in PYG.
    items = [
        {
            "descripcion": "Producto caro",
            "cantidad": "1",
            "precio_unitario": "7000000",
            "afectacion": "gravado",
            "tasa": 10,
        }
    ]

    with pytest.raises(SifenValidationError, match="innominado_over_limit"):
        _build(factura_payload(cliente=dict(_INNOMINADO), items=items))


def test_innominado_limit_does_not_apply_to_medical_samples() -> None:
    items = [
        {
            "descripcion": "Muestra medica",
            "cantidad": "1",
            "precio_unitario": "8000000",
            "afectacion": "gravado",
            "tasa": 10,
        }
    ]

    root = _build(
        factura_payload(
            cliente=dict(_INNOMINADO), items=items, tipo_transaccion="muestras_medicas"
        )
    )

    assert _receiver(root)["iTipIDRec"] == "5"


def test_innominado_receiver_is_refused_in_a_credit_note() -> None:
    payload = factura_payload(
        cliente=dict(_INNOMINADO),
        documento_asociado={"cdc": "01800123450001001000000012026010112345678901"},
    )

    with pytest.raises(SifenValidationError, match="innominado_not_allowed"):
        _build(payload, contract="nota_credito_v1")


def test_b2f_receiver_keeps_its_document_and_skips_department_and_city() -> None:
    cliente = {
        "naturaleza": 2,
        "tipo_operacion": 4,
        "tipo_documento_identidad": 2,
        "numero_documento_identidad": "X1234567",
        "nombre": "FOREIGN CUSTOMER LLC",
        "pais_codigo": "ARG",
        "direccion": "AV. FICTICIA",
        "numero_casa": "100",
    }

    receiver = _receiver(_build(factura_payload(cliente=cliente)))

    assert receiver["cPaisRec"] == "ARG"
    assert receiver["dDesPaisRe"] == "Argentina"
    assert receiver["iTipIDRec"] == "2"  # NT 23 1335
    assert receiver["dDirRec"] == "AV. FICTICIA"
    assert "cDepRec" not in receiver and "cCiuRec" not in receiver  # NT 03


def test_taxpayer_receiver_always_carries_its_dv() -> None:
    receiver = _receiver(_build(factura_payload()))

    assert receiver["iTiContRec"] == "2"
    assert receiver["dRucRec"] == "80025298"
    assert receiver["dDVRec"] == "5"


def test_b2g_without_public_procurement_data_is_built() -> None:
    # NT 26: gCompPub (E020) is optional in B2G.
    cliente = {**factura_payload()["cliente"], "tipo_operacion": 3}

    root = _build(factura_payload(cliente=cliente))

    assert root.find("s:DE/s:gDtipDE/s:gCamFE/s:gCompPub", _NS) is None
    assert _receiver(root)["iTiOpe"] == "3"


def test_generation_responsible_with_other_document_type() -> None:
    responsable = {
        "tipo_documento": 9,
        "descripcion_tipo_documento": "Licencia de conducir",
        "numero_documento": "LC-998877",
        "nombre": "RESPONSABLE FICTICIO",
        "cargo": "CAJERO",
    }

    root = _build(factura_payload(emisor={"responsable_generacion": responsable}))

    gresp = root.find("s:DE/s:gDatGralOpe/s:gEmis/s:gRespDE", _NS)
    assert gresp.find("s:iTipIDRespDE", _NS).text == "9"
    assert gresp.find("s:dDTipIDRespDE", _NS).text == "Licencia de conducir"
    assert gresp.find("s:dCarRespDE", _NS).text == "CAJERO"


@pytest.mark.parametrize(
    "changes",
    [
        {"tipo_documento": 5},  # XSD tiTipIDRespDE: [1-4]|9
        {"tipo_documento": None},  # no default document type
        {"tipo_documento": 9},  # 9 needs its description (1265)
        {"cargo": "JEF"},  # tdCargo: 4-100
    ],
)
def test_generation_responsible_outside_the_xsd_is_refused(changes: dict) -> None:
    responsable = {
        "tipo_documento": 1,
        "numero_documento": "1234567",
        "nombre": "RESPONSABLE FICTICIO",
        "cargo": "CAJERO",
        **changes,
    }

    with pytest.raises(SifenValidationError, match="responsable_generacion"):
        _build(factura_payload(emisor={"responsable_generacion": responsable}))
