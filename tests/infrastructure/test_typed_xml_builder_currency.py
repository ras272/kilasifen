"""Currency descriptions as the builder writes them (MT v150 1206/1555)."""

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
_USD = {"moneda": "USD", "condicion_tipo_cambio": 1, "tipo_cambio": "7300"}


def _build(payload: dict) -> ET.Element:
    result = build_typed_document_xml(
        document=typed_document(payload),
        emitter=fictional_emitter(),
        stamping=fictional_stamping(),
    )
    assert result is not None
    return ET.fromstring(result.generated_xml.encode("utf-8"))


def _text(root: ET.Element, path: str) -> str | None:
    node = root.find(path, _NS)
    assert node is not None
    return node.text


def _usd_item() -> dict:
    return {
        "descripcion": "Producto",
        "cantidad": "1",
        "precio_unitario": "100",
        "afectacion": "gravado",
        "tasa": 10,
    }


def test_currency_descriptions_are_the_official_iso_names() -> None:
    root = _build(
        factura_payload(
            items=[_usd_item()],
            condicion_operacion={
                "tipo": "credito",
                "credito": {
                    "tipo": "cuotas",
                    "cuotas": [{"monto": "100", "moneda": "USD"}],
                },
            },
            **_USD,
        )
    )

    # D016/E654 are "Referente al campo" D015/E653 and 1206 checks the match:
    # the CodeName of Monedas_v150.xsd, not a free translation ("Dólar").
    assert _text(root, "s:DE/s:gDatGralOpe/s:gOpeCom/s:dDesMoneOpe") == "US Dollar"
    cuota = "s:DE/s:gDtipDE/s:gCamCond/s:gPagCred/s:gCuotas/s:dDMoneCuo"
    assert _text(root, cuota) == "US Dollar"


def test_payment_description_ignores_the_caller_text() -> None:
    root = _build(
        factura_payload(
            condicion_operacion={
                "tipo": "contado",
                "formas_pago": [
                    {
                        "tipo": "efectivo",
                        "monto": "110000",
                        "moneda": "PYG",
                        "moneda_descripcion": "Guaranies paraguayos",
                    }
                ],
            }
        )
    )

    # 1555: dDMoneTiPag matches E609.
    payment = "s:DE/s:gDtipDE/s:gCamCond/s:gPaConEIni/s:dDMoneTiPag"
    assert _text(root, payment) == "Guarani"


@pytest.mark.parametrize("currency", ["XYZ", "BMD"])
def test_currency_without_an_official_short_name_is_a_local_failure(
    currency: str,
) -> None:
    # XYZ is not in cMondT; the CodeName of BMD exceeds the 20 characters.
    with pytest.raises(SifenValidationError, match="moneda.unsupported"):
        _build(
            factura_payload(
                moneda=currency, condicion_tipo_cambio=1, tipo_cambio="1000"
            )
        )
