"""Tests for deterministic XML schema validation."""
from __future__ import annotations

from pathlib import Path

from pysifen.CommonMixin import CommonMixin
from pysifen.sdk.validation import resolve_schema_path, validate_xml

SAMPLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "pysifen"
    / "de"
    / "samples"
    / "v150"
    / "factura_electronica.xml"
)


def _build_valid_rde_xml() -> str:
    """Patch sample XML to satisfy current v150 schema constraints."""
    xml = SAMPLE_PATH.read_text(encoding="utf-8")
    replacements = [
        (
            "<dFecFirma>2024-11-29T17:59:57</dFecFirma>\n    <gOpeDE>",
            (
                "<dFecFirma>2024-11-29T17:59:57</dFecFirma>\n"
                "    <dSisFact>1</dSisFact>\n"
                "    <gOpeDE>"
            ),
        ),
        ("<dFeFinT>2025-12-31</dFeFinT>", ""),
        (
            "<gValorItem>\n"
            "          <dPUniProSer>500000</dPUniProSer>\n"
            "          <dDescItem>0</dDescItem>\n"
            "          <dTotOpeItem>1000000</dTotOpeItem>\n"
            "          <dTotOpeGs>1000000</dTotOpeGs>\n"
            "        </gValorItem>",
            (
                "<gValorItem>\n"
                "          <dPUniProSer>500000</dPUniProSer>\n"
                "          <dTotBruOpeItem>1000000</dTotBruOpeItem>\n"
                "          <gValorRestaItem>\n"
                "            <dDescItem>0</dDescItem>\n"
                "            <dTotOpeItem>1000000</dTotOpeItem>\n"
                "            <dTotOpeGs>1000000</dTotOpeGs>\n"
                "          </gValorRestaItem>\n"
                "        </gValorItem>"
            ),
        ),
        (
            "<gValorItem>\n"
            "          <dPUniProSer>150000</dPUniProSer>\n"
            "          <dDescItem>0</dDescItem>\n"
            "          <dTotOpeItem>150000</dTotOpeItem>\n"
            "          <dTotOpeGs>150000</dTotOpeGs>\n"
            "        </gValorItem>",
            (
                "<gValorItem>\n"
                "          <dPUniProSer>150000</dPUniProSer>\n"
                "          <dTotBruOpeItem>150000</dTotBruOpeItem>\n"
                "          <gValorRestaItem>\n"
                "            <dDescItem>0</dDescItem>\n"
                "            <dTotOpeItem>150000</dTotOpeItem>\n"
                "            <dTotOpeGs>150000</dTotOpeGs>\n"
                "          </gValorRestaItem>\n"
                "        </gValorItem>"
            ),
        ),
        (
            "<dLiqIVAItem>90909</dLiqIVAItem>\n        </gCamIVA>",
            (
                "<dLiqIVAItem>90909</dLiqIVAItem>\n"
                "          <dBasExe>0</dBasExe>\n"
                "        </gCamIVA>"
            ),
        ),
        (
            "<dLiqIVAItem>13636</dLiqIVAItem>\n        </gCamIVA>",
            (
                "<dLiqIVAItem>13636</dLiqIVAItem>\n"
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
                "<dTotGralOpe>1150000</dTotGralOpe>\n"
                "      <dIVA10>104545</dIVA10>\n"
                "      <dBaseGrav10>1045455</dBaseGrav10>\n"
                "      <dTBasGraIVA>1045455</dTBasGraIVA>\n"
                "      <dTotIVA>104545</dTotIVA>\n"
                "      <dTotalGs>1150000</dTotalGs>"
            ),
            (
                "<dTotGralOpe>1150000</dTotGralOpe>\n"
                "      <dIVA10>104545</dIVA10>\n"
                "      <dTotIVA>104545</dTotIVA>\n"
                "      <dBaseGrav10>1045455</dBaseGrav10>\n"
                "      <dTBasGraIVA>1045455</dTBasGraIVA>\n"
                "      <dTotalGs>1150000</dTotalGs>"
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


class DummyXml(CommonMixin):
    """Minimal wrapper to exercise CommonMixin.validate_xml()."""

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
