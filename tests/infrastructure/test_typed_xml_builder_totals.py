"""gCamIVA, gTotSub and gCamCond as the builder writes them (F40-F46)."""

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


def _item(**changes) -> dict:
    item = {
        "descripcion": "Producto",
        "cantidad": "1",
        "precio_unitario": "110000",
        "afectacion": "gravado",
        "tasa": 10,
    }
    item.update(changes)
    return item


def _fields(node: ET.Element | None) -> dict[str, str]:
    assert node is not None
    return {child.tag.split("}")[1]: child.text for child in node if len(child) == 0}


def _item_iva(root: ET.Element, index: int = 0) -> dict[str, str]:
    items = root.findall("s:DE/s:gDtipDE/s:gCamItem", _NS)
    return _fields(items[index].find("s:gCamIVA", _NS))


def _totals(root: ET.Element) -> dict[str, str]:
    return _fields(root.find("s:DE/s:gTotSub", _NS))


def _children(node: ET.Element | None) -> list[str]:
    assert node is not None
    return [child.tag.split("}")[1] for child in node]


def test_exempt_and_exonerated_items_carry_proportion_and_bases_zero() -> None:
    root = _build(
        factura_payload(
            items=[
                _item(afectacion="exento", tasa=0, precio_unitario="20000"),
                _item(afectacion="exonerado", tasa=0, precio_unitario="15000"),
            ]
        )
    )

    exempt, exonerated = _item_iva(root, 0), _item_iva(root, 1)
    # 1905 (E733 = 0) and NT 13 / 1921 (E737 = 0 for E731 = 2 or 3).
    assert exempt["dPropIVA"] == exonerated["dPropIVA"] == "0"
    assert exempt["dBasExe"] == exonerated["dBasExe"] == "0"
    # E732 as corrected by NT 10 §5.1 (Tabla 6) and XSD tdDesAfecIVA.
    assert exonerated["dDesAfecIVA"] == "Exonerado (Art. 100 - Ley 6380/2019)"
    totals = _totals(root)
    assert totals["dSubExe"] == "20000"
    assert totals["dSubExo"] == "15000"
    assert "dIVA10" not in totals and "dTotIVA" not in totals


def test_partial_item_and_its_subtotals_follow_nt13() -> None:
    root = _build(
        factura_payload(
            items=[
                _item(
                    precio_unitario="100000",
                    afectacion="gravado_parcial",
                    proporcion_gravada="30",
                )
            ]
        )
    )

    iva = _item_iva(root)
    assert iva["dPropIVA"] == "30"
    assert iva["dBasGravIVA"] == "29126.21"
    assert iva["dLiqIVAItem"] == "2912.62"
    assert iva["dBasExe"] == "67961.17"
    totals = _totals(root)
    assert totals["dSubExe"] == "67961.17"  # 2353: E737 of E731=4
    assert totals["dSub10"] == "32038.83"  # 2359: E735 + E736
    assert totals["dTotOpe"] == "100000"


def test_partial_item_without_proportion_is_a_local_failure() -> None:
    with pytest.raises(SifenValidationError, match="proporcion_gravada_required"):
        _build(factura_payload(items=[_item(afectacion="gravado_parcial")]))


def test_iva_keeps_decimals_and_totals_are_their_exact_sum() -> None:
    root = _build(factura_payload(items=[_item(precio_unitario="16")]))

    iva = _item_iva(root)
    # R3 §3.2: 16 Gs at 10 % gave E735 = 15 and E736 = 1 (15 * 0.1 = 1.5).
    # PYG carries 2 decimals (decision F42): E735 = 1600/110 = 14.5454... ->
    # 14.55 and E736 = 14.55 * 0.1 = 1.455 -> 1.46.
    assert iva["dBasGravIVA"] == "14.55"
    assert iva["dLiqIVAItem"] == "1.46"
    totals = _totals(root)
    assert totals["dIVA10"] == totals["dTotIVA"] == "1.46"
    assert totals["dBaseGrav10"] == totals["dTBasGraIVA"] == "14.55"


def test_zero_valued_subtotals_are_written_when_an_item_needs_them() -> None:
    # 2356/2366/2370/2372/2376: a 0 Gs item at 5 % next to a taxed one.
    root = _build(
        factura_payload(
            items=[_item(), _item(precio_unitario="0", tasa=5, descripcion="Regalo")]
        )
    )

    totals = _totals(root)
    assert totals["dSub5"] == "0"
    assert totals["dIVA5"] == "0"
    assert totals["dBaseGrav5"] == "0"
    assert totals["dTotIVA"] == "10000"
    assert "dSubExe" not in totals and "dSubExo" not in totals


def test_global_discount_percentage_feeds_every_item() -> None:
    root = _build(
        factura_payload(
            porcentaje_descuento_global="10",
            items=[
                _item(precio_unitario="90000"),
                _item(precio_unitario="70000", descuento_particular="7000"),
            ],
        )
    )

    items = root.findall(
        "s:DE/s:gDtipDE/s:gCamItem/s:gValorItem/s:gValorRestaItem", _NS
    )
    assert [_fields(item)["dDescGloItem"] for item in items] == ["9000", "7000"]
    totals = _totals(root)
    assert totals["dPorcDescTotal"] == "10"  # F010 (NT 01, 1860/1862)
    assert totals["dTotDesc"] == "7000"
    assert totals["dTotDescGlotem"] == "16000"
    assert totals["dDescTotal"] == "23000"


def test_rounding_is_zero_unless_the_caller_asks_for_it() -> None:
    plain = _totals(_build(factura_payload(items=[_item(precio_unitario="107437")])))
    rounded = _totals(
        _build(
            factura_payload(
                items=[_item(precio_unitario="107437")], redondeo="multiplo_50"
            )
        )
    )

    assert (plain["dRedon"], plain["dTotGralOpe"]) == ("0", "107437")
    assert (rounded["dRedon"], rounded["dTotGralOpe"]) == ("37", "107400")


def test_foreign_currency_rounding_is_a_local_failure() -> None:
    with pytest.raises(SifenValidationError, match="redondeo.only_pyg"):
        _build(
            factura_payload(
                items=[_item(precio_unitario="100.49")], redondeo="multiplo_50", **_USD
            )
        )


def test_credit_initial_delivery_writes_its_payments_before_gpagcred() -> None:
    root = _build(
        factura_payload(
            condicion_operacion={
                "tipo": "credito",
                "formas_pago": [{"tipo": "efectivo", "monto": "10000"}],
                "credito": {
                    "tipo": "cuotas",
                    "monto_entrega_inicial": "10000",
                    "cuotas": [{"monto": "50000"}, {"monto": "50000"}],
                },
            }
        )
    )

    condition = root.find("s:DE/s:gDtipDE/s:gCamCond", _NS)
    # 1551 and XSD tgCamCond: gPaConEIni before gPagCred.
    assert _children(condition) == ["iCondOpe", "dDCondOpe", "gPaConEIni", "gPagCred"]
    payment = _fields(condition.find("s:gPaConEIni", _NS))
    assert payment["dMonTiPag"] == "10000"
    assert "dTiCamTiPag" not in payment
    credit = _fields(condition.find("s:gPagCred", _NS))
    assert credit["dMonEnt"] == "10000"


def test_payment_rate_depends_on_the_currency_of_the_payment() -> None:
    root = _build(
        factura_payload(
            items=[_item(precio_unitario="100")],
            condicion_operacion={
                "tipo": "contado",
                "formas_pago": [
                    {"tipo": "efectivo", "monto": "365000", "moneda": "PYG"},
                    {"tipo": "transferencia", "monto": "50"},
                ],
            },
            **_USD,
        )
    )

    payments = [
        _fields(node)
        for node in root.findall("s:DE/s:gDtipDE/s:gCamCond/s:gPaConEIni", _NS)
    ]
    # 1557: no dTiCamTiPag for the guaranies; 1556: mandatory for the dollars.
    assert "dTiCamTiPag" not in payments[0]
    assert payments[1]["cMoneTiPag"] == "USD"
    assert payments[1]["dTiCamTiPag"] == "7300"


def test_isc_is_a_local_failure() -> None:
    # 1902: no gCamIVA with D013 = 2, and F008 would be the missing F006.
    with pytest.raises(SifenValidationError, match="isc_not_supported"):
        _build(factura_payload(tipo_impuesto="isc"))
