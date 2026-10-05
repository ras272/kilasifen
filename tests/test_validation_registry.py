"""Tests for deterministic XML schema validation."""
from __future__ import annotations

from pathlib import Path

from kilasifen.engine.binding import BindingMixin
from kilasifen.engine.sdk.validation import resolve_schema_path, validate_xml
from tests._muestras import FACTURA

SAMPLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kilasifen"
    / "engine"
    / "de"
    / "samples"
    / "v150"
    / "factura_electronica.xml"
)
_ITEM_1, _ITEM_2 = FACTURA.items


def _build_valid_rde_xml() -> str:
    """Patch sample XML to satisfy current v150 schema constraints."""
    xml = SAMPLE_PATH.read_text(encoding="utf-8")
    replacements = [
        (
            f"<dFecFirma>{FACTURA.fecha_firma}</dFecFirma>\n    <gOpeDE>",
            (
                f"<dFecFirma>{FACTURA.fecha_firma}</dFecFirma>\n"
                "    <dSisFact>1</dSisFact>\n"
                "    <gOpeDE>"
            ),
        ),
        (f"<dFeFinT>{FACTURA.fin_timbrado}</dFeFinT>", ""),
        (
            "<gValorItem>\n"
            f"          <dPUniProSer>{_ITEM_1.precio_unitario}</dPUniProSer>\n"
            "          <dDescItem>0</dDescItem>\n"
            f"          <dTotOpeItem>{_ITEM_1.total}</dTotOpeItem>\n"
            f"          <dTotOpeGs>{_ITEM_1.total}</dTotOpeGs>\n"
            "        </gValorItem>",
            (
                "<gValorItem>\n"
                f"          <dPUniProSer>{_ITEM_1.precio_unitario}</dPUniProSer>\n"
                f"          <dTotBruOpeItem>{_ITEM_1.total}</dTotBruOpeItem>\n"
                "          <gValorRestaItem>\n"
                "            <dDescItem>0</dDescItem>\n"
                f"            <dTotOpeItem>{_ITEM_1.total}</dTotOpeItem>\n"
                f"            <dTotOpeGs>{_ITEM_1.total}</dTotOpeGs>\n"
                "          </gValorRestaItem>\n"
                "        </gValorItem>"
            ),
        ),
        (
            "<gValorItem>\n"
            f"          <dPUniProSer>{_ITEM_2.precio_unitario}</dPUniProSer>\n"
            "          <dDescItem>0</dDescItem>\n"
            f"          <dTotOpeItem>{_ITEM_2.total}</dTotOpeItem>\n"
            f"          <dTotOpeGs>{_ITEM_2.total}</dTotOpeGs>\n"
            "        </gValorItem>",
            (
                "<gValorItem>\n"
                f"          <dPUniProSer>{_ITEM_2.precio_unitario}</dPUniProSer>\n"
                f"          <dTotBruOpeItem>{_ITEM_2.total}</dTotBruOpeItem>\n"
                "          <gValorRestaItem>\n"
                "            <dDescItem>0</dDescItem>\n"
                f"            <dTotOpeItem>{_ITEM_2.total}</dTotOpeItem>\n"
                f"            <dTotOpeGs>{_ITEM_2.total}</dTotOpeGs>\n"
                "          </gValorRestaItem>\n"
                "        </gValorItem>"
            ),
        ),
        (
            f"<dLiqIVAItem>{_ITEM_1.iva}</dLiqIVAItem>\n        </gCamIVA>",
            (
                f"<dLiqIVAItem>{_ITEM_1.iva}</dLiqIVAItem>\n"
                "          <dBasExe>0</dBasExe>\n"
                "        </gCamIVA>"
            ),
        ),
        (
            f"<dLiqIVAItem>{_ITEM_2.iva}</dLiqIVAItem>\n        </gCamIVA>",
            (
                f"<dLiqIVAItem>{_ITEM_2.iva}</dLiqIVAItem>\n"
                "          <dBasExe>0</dBasExe>\n"
                "        </gCamIVA>"
            ),
        ),
        (
            "<dTotDesc>0</dTotDesc>\n      <dPorcDescTotal>0</dPorcDescTotal>",
            (
                "<dTotDesc>0</dTotDesc>\n"
                "      <dTotDescGlotem>0</dTotDescGlotem>\n"
                "      <dTotAntItem>0</dTotAntItem>\n"
                "      <dTotAnt>0</dTotAnt>\n"
                "      <dPorcDescTotal>0</dPorcDescTotal>"
            ),
        ),
        (
            (
                f"<dTotGralOpe>{FACTURA.total_general}</dTotGralOpe>\n"
                f"      <dIVA10>{FACTURA.iva_10}</dIVA10>\n"
                f"      <dBaseGrav10>{FACTURA.base_gravada_10}</dBaseGrav10>\n"
                f"      <dTBasGraIVA>{FACTURA.base_gravada_10}</dTBasGraIVA>\n"
                f"      <dTotIVA>{FACTURA.total_iva}</dTotIVA>\n"
                f"      <dTotalGs>{FACTURA.total_general}</dTotalGs>"
            ),
            (
                f"<dTotGralOpe>{FACTURA.total_general}</dTotGralOpe>\n"
                f"      <dIVA10>{FACTURA.iva_10}</dIVA10>\n"
                f"      <dTotIVA>{FACTURA.total_iva}</dTotIVA>\n"
                f"      <dBaseGrav10>{FACTURA.base_gravada_10}</dBaseGrav10>\n"
                f"      <dTBasGraIVA>{FACTURA.base_gravada_10}</dTBasGraIVA>\n"
                f"      <dTotalGs>{FACTURA.total_general}</dTotalGs>"
            ),
        ),
        (
            "<ds:DigestValue>PLACEHOLDER</ds:DigestValue>",
            "<ds:DigestValue>QUJD</ds:DigestValue>",
        ),
        (
            "<ds:SignatureValue>PLACEHOLDER</ds:SignatureValue>",
            "<ds:SignatureValue>QUJDRA==</ds:SignatureValue>",
        ),
        (
            (
                "<dCarQR>https://ekuatia.set.gov.py/consultas/qr?"
                "nVersion=150</dCarQR>"
            ),
            (
                "<dCarQR>https://ekuatia.set.gov.py/consultas/qr?nVersion=150"
                "&amp;codigo="
                "1234567890ABCDEFGHIJ1234567890ABCDEFGHIJ1234567890"
                "ABCDEFGHIJ1234567890ABCDEFGHIJ</dCarQR>"
            ),
        ),
    ]
    for old, new in replacements:
        xml = xml.replace(old, new)
    return xml


class DummyXml(BindingMixin):
    """Minimal wrapper to exercise BindingMixin.validate_xml()."""

    def __init__(self, xml: str):
        self._xml = xml

    def to_xml(self, pretty_print: bool = True) -> str:
        return self._xml


def test_rde_root_resolves_to_si_recep_de_v150():
    schema_path = resolve_schema_path("rDE", schema_version="v150")
    assert schema_path is not None
    assert schema_path.name == "siRecepDE_v150.xsd"


def test_validate_sample_rde_returns_no_errors():
    xml = _build_valid_rde_xml()
    assert DummyXml(xml).validate_xml() == []


def test_invalid_xml_returns_reproducible_errors():
    xml = _build_valid_rde_xml().replace(
        "<dSisFact>1</dSisFact>",
        "<dSisFact>2</dSisFact>",
    )
    first = validate_xml(xml)
    second = validate_xml(xml)

    assert first
    assert first == second
    assert any("dSisFact" in error for error in first)
