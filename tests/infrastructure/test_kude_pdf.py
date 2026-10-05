"""Tests for the SIFEN KuDE PDF renderer."""

import copy
import re
import zlib
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.kude import pdf_renderer
from kilasifen.infrastructure.kude.data_extractor import extract_kude_data
from kilasifen.infrastructure.kude.pdf_renderer import render_kude_pdf
from kilasifen.testing.typed_contract_scenarios import get_typed_contract_scenarios

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"


def _emitter(*, ambiente: str = "test") -> Emitter:
    ts = datetime.now(timezone.utc)
    return Emitter(
        id="emitter-1",
        external_id="erp-test",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment=ambiente,
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=ts,
        updated_at=ts,
    )


def _document_for_scenario(name: str, doc_type: str) -> Document:
    signed_xml = (_GOLDEN_DIR / f"{name}.xml").read_text(encoding="utf-8")
    ts = datetime.now(timezone.utc)
    return Document(
        id=f"doc-{name}",
        emitter_id="emitter-1",
        external_id=f"erp-{name}",
        idempotency_key=f"idem-{name}",
        document_type=doc_type,
        payload_snapshot={"signed_xml": signed_xml},
        generated_xml=None,
        signed_xml=signed_xml,
        sifen_request_xml=None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=None,
        internal_status="approved",
        sifen_status="approved",
        sifen_result_code="0260",
        sifen_result_message="OK",
        created_at=ts,
        updated_at=ts,
        establishment="001",
        point="001",
        document_number=1,
    )


@pytest.mark.parametrize(
    "scenario",
    get_typed_contract_scenarios(),
    ids=lambda s: s.name,
)
def test_render_kude_pdf_succeeds_for_all_golden_scenarios(scenario):
    pdf = render_kude_pdf(
        document=_document_for_scenario(scenario.name, scenario.document_type),
        emitter=_emitter(),
    )
    assert pdf[:5] == b"%PDF-"
    assert 1024 < len(pdf) < 200_000


def test_render_kude_pdf_for_nota_credito_contains_label():
    pdf = render_kude_pdf(
        document=_document_for_scenario("nc_total", "nota_credito"),
        emitter=_emitter(),
    )
    # PDF text streams use FlateDecode by default; assert via extracted data label.
    data = extract_kude_data(
        document=_document_for_scenario("nc_total", "nota_credito"),
        emitter=_emitter(),
    )
    assert data["kude"]["tipo_label"] == "KuDE de Nota de Crédito Electrónica"
    # Sanity: PDF was actually produced.
    assert pdf.startswith(b"%PDF-")


def test_render_kude_pdf_for_nota_debito_contains_label():
    document = _document_for_scenario("nd_recupero_costo", "nota_debito")
    pdf = render_kude_pdf(document=document, emitter=_emitter())
    data = extract_kude_data(document=document, emitter=_emitter())
    assert data["kude"]["tipo_label"] == "KuDE de Nota de Débito Electrónica"
    assert data["kude"]["nota_debito"]["motivo_codigo"] == 6
    assert pdf.startswith(b"%PDF-")


def test_render_kude_pdf_for_test_environment_includes_warning_data():
    document = _document_for_scenario("factura_b2b_iva10", "factura")
    data = extract_kude_data(document=document, emitter=_emitter(ambiente="test"))
    assert data["kude"]["ambiente"] == "test"
    assert data["kude"]["ambiente_warning"]
    pdf = render_kude_pdf(document=document, emitter=_emitter(ambiente="test"))
    assert pdf.startswith(b"%PDF-")


def test_extract_kude_data_does_not_expose_csc():
    document = _document_for_scenario("factura_b2b_iva10", "factura")
    emitter = _emitter()
    data = extract_kude_data(document=document, emitter=emitter)
    assert emitter.csc not in repr(data)


# ---------------------------------------------------------------------------
# Multi-page KuDE (MT v150 §13.3 p. 194)
# ---------------------------------------------------------------------------

_SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"


def _with_items(scenario: str, count: int) -> Document:
    """Golden signed XML with its first item repeated ``count`` times."""

    ET.register_namespace("", _SIFEN_NS)
    root = ET.fromstring((_GOLDEN_DIR / f"{scenario}.xml").read_bytes())
    dtip = root.find(f"{{{_SIFEN_NS}}}DE/{{{_SIFEN_NS}}}gDtipDE")
    item = dtip.find(f"{{{_SIFEN_NS}}}gCamItem")
    position = list(dtip).index(item)
    for offset in range(1, count):
        dtip.insert(position + offset, copy.deepcopy(item))
    signed_xml = ET.tostring(root, encoding="unicode")
    return replace(
        _document_for_scenario(scenario, "factura"),
        signed_xml=signed_xml,
        payload_snapshot={"signed_xml": signed_xml},
    )


def _record_drawing(monkeypatch) -> list[tuple[int, str]]:
    """Record (page, text) for every cell and (page, "<image>") for images."""

    drawn: list[tuple[int, str]] = []
    original_cell = pdf_renderer._KudePdf.cell
    original_image = pdf_renderer._KudePdf.image

    def cell(self, *args, **kwargs):
        text = kwargs.get("text", args[2] if len(args) > 2 else "")
        drawn.append((self.page_no(), str(text)))
        return original_cell(self, *args, **kwargs)

    def image(self, *args, **kwargs):
        drawn.append((self.page_no(), "<image>"))
        return original_image(self, *args, **kwargs)

    monkeypatch.setattr(pdf_renderer._KudePdf, "cell", cell)
    monkeypatch.setattr(pdf_renderer._KudePdf, "image", image)
    return drawn


def _page_count(pdf: bytes) -> int:
    return int(re.search(rb"/Count (\d+)", pdf).group(1))


def _texts(pdf: bytes) -> list[str]:
    """Text of every BT..ET block of the inflated page contents."""

    texts = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            content = zlib.decompress(match.group(1))
        except zlib.error:
            continue
        for block in re.findall(rb"BT(.*?)ET", content, re.S):
            parts = re.findall(rb"\((.*?)\) Tj", block, re.S)
            if parts:
                texts.append(b"".join(parts).decode("latin-1"))
    return texts


def test_multi_page_kude_prints_the_qr_on_the_first_page(monkeypatch):
    drawn = _record_drawing(monkeypatch)

    pdf = render_kude_pdf(
        document=_with_items("factura_b2b_iva10", 90), emitter=_emitter()
    )

    assert _page_count(pdf) >= 3
    assert [page for page, text in drawn if text == "<image>"] == [1]


def test_multi_page_kude_numbers_every_page_over_the_total(monkeypatch):
    pdf = render_kude_pdf(
        document=_with_items("factura_b2b_iva10", 90), emitter=_emitter()
    )

    total = _page_count(pdf)
    numbers = [text for text in _texts(pdf) if text.startswith("Página ")]
    assert numbers == [f"Página {page}/{total}" for page in range(1, total + 1)]


def test_multi_page_kude_keeps_the_totals_and_closing_notice_on_the_last_page(
    monkeypatch,
):
    drawn = _record_drawing(monkeypatch)

    pdf = render_kude_pdf(
        document=_with_items("factura_b2b_iva10", 90), emitter=_emitter()
    )

    last = _page_count(pdf)
    totals = [page for page, text in drawn if text in {"Subtotal exentas", "Total IVA"}]
    assert totals == [last, last]
    notices = [page for page, text in drawn if "Fiscal Auxiliar" in text]
    assert notices == [last]


def test_multi_page_kude_repeats_the_items_header_and_never_splits_a_row(
    monkeypatch,
):
    drawn = _record_drawing(monkeypatch)

    render_kude_pdf(document=_with_items("factura_b2b_iva10", 90), emitter=_emitter())

    item_pages = {page for page, text in drawn if text == "A-001"}
    header_pages = {page for page, text in drawn if text == "Cód."}
    assert len(item_pages) >= 2
    assert header_pages == item_pages
    row_size = len(pdf_renderer._ITEM_HEADERS)
    rows = [index for index, (_, text) in enumerate(drawn) if text == "A-001"]
    assert len(rows) == 90
    for index in rows:
        assert len({page for page, _ in drawn[index : index + row_size]}) == 1


def test_single_page_kude_reads_one_of_one():
    pdf = render_kude_pdf(
        document=_document_for_scenario("factura_b2b_iva10", "factura"),
        emitter=_emitter(),
    )

    assert _page_count(pdf) == 1
    assert "Página 1/1" in _texts(pdf)


# ---------------------------------------------------------------------------
# Amounts, total in guaranies and stamping date (MT v150 §13.4; NT 10 §1.11)
# ---------------------------------------------------------------------------


def _drawn_texts(monkeypatch, document: Document) -> list[str]:
    drawn = _record_drawing(monkeypatch)
    render_kude_pdf(document=document, emitter=_emitter())
    return [text for _, text in drawn]


def _with_signed_xml(document: Document, signed_xml: str) -> Document:
    return replace(
        document, signed_xml=signed_xml, payload_snapshot={"signed_xml": signed_xml}
    )


def _undo_separators(printed: str) -> str:
    return printed.replace(".", "").replace(",", ".")


def _printed_after(texts: list[str], label: str) -> str:
    return texts[texts.index(label) + 1]


def test_pyg_kude_prints_every_decimal_of_the_xml(monkeypatch):
    texts = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_b2b_iva10", "factura")
    )

    # dIVA10 is 9090.90909091 in the XML (NT 13): MT v150 §13.2 forbids a
    # rounded 9.091, which is in no field of the signed XML.
    assert _printed_after(texts, "Liquidación IVA 10%") == "9.090,90909091"
    assert "9.091" not in texts
    assert _printed_after(texts, "TOTAL EN GUARANÍES") == "100.000"
    assert not any(text.startswith("TOTAL PYG") for text in texts)


def test_nc_parcial_kude_prints_the_iva_of_the_xml_and_adds_up(monkeypatch):
    # The KuDE must match the DTE (MT v150 §6.6): dIVA5 952.38095238, dIVA10
    # 2727.27272727 and dTotIVA 3679.65367965, so F017 = F015 + F016 (2371)
    # holds on paper too.
    texts = _drawn_texts(
        monkeypatch, _document_for_scenario("nc_parcial", "nota_credito")
    )

    iva_5 = _printed_after(texts, "Liquidación IVA 5%")
    iva_10 = _printed_after(texts, "Liquidación IVA 10%")
    total = _printed_after(texts, "Total IVA")
    assert iva_5 == "952,38095238"
    assert iva_10 == "2.727,27272727"
    assert total == "3.679,65367965"
    assert Decimal(_undo_separators(iva_5)) + Decimal(
        _undo_separators(iva_10)
    ) == Decimal(_undo_separators(total))


def test_foreign_currency_kude_prints_f014_and_f023_as_total_in_guaranies(
    monkeypatch,
):
    texts = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_moneda_usd", "factura")
    )

    # F014 = 120.5 USD, F023 dTotalGs = 879650 (NT 08 §1.2), F017 10.95454546.
    assert _printed_after(texts, "TOTAL USD") == "120,5"
    assert _printed_after(texts, "TOTAL EN GUARANÍES") == "879.650"
    assert _printed_after(texts, "Total IVA") == "10,95454546"


_TOTAL_FIELDS = {
    "Subtotal exentas": "dSubExe",
    "Subtotal exonerado": "dSubExo",
    "Subtotal 5%": "dSub5",
    "Subtotal 10%": "dSub10",
    "Total operación": "dTotOpe",
    "Redondeo": "dRedon",
    "Liquidación IVA 5%": "dIVA5",
    "Liquidación IVA 10%": "dIVA10",
    "Total IVA": "dTotIVA",
}


@pytest.mark.parametrize(
    "scenario",
    get_typed_contract_scenarios(),
    ids=lambda s: s.name,
)
def test_every_printed_total_is_the_xml_literal_and_they_add_up(monkeypatch, scenario):
    document = _document_for_scenario(scenario.name, scenario.document_type)
    texts = _drawn_texts(monkeypatch, document)
    totals = ET.fromstring(document.signed_xml).find(
        f"{{{_SIFEN_NS}}}DE/{{{_SIFEN_NS}}}gTotSub"
    )

    printed = {}
    for label, field in _TOTAL_FIELDS.items():
        if label not in texts:
            continue
        value = _printed_after(texts, label)
        literal = totals.findtext(f"{{{_SIFEN_NS}}}{field}") or "0"
        # MT v150 §13.2: digit for digit, only the separators change.
        assert _undo_separators(value) == literal, (label, value, literal)
        printed[field] = Decimal(literal)

    # F008 = F002 + F003 + F004 + F005 and F014 = F008 - F013 (MT v150
    # pp. 102-104): the printed figures add up as the XML does.
    subtotals = ("dSubExe", "dSubExo", "dSub5", "dSub10")
    assert sum(printed.get(field, 0) for field in subtotals) == printed["dTotOpe"]
    general = totals.findtext(f"{{{_SIFEN_NS}}}dTotGralOpe")
    assert printed["dTotOpe"] - printed.get("dRedon", 0) == Decimal(general)


def test_kude_prints_the_rounding_and_the_exonerated_subtotal(monkeypatch):
    rounding = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_redondeo_50", "factura")
    )
    exonerated = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_iva_parcial_exonerado", "factura")
    )

    assert _printed_after(rounding, "Total operación") == "107.437"
    assert _printed_after(rounding, "Redondeo") == "37"
    assert _printed_after(rounding, "TOTAL EN GUARANÍES") == "107.400"
    assert _printed_after(exonerated, "Subtotal exonerado") == "15.000"
    assert _printed_after(exonerated, "Subtotal exentas") == "67.961,16504855"
    # dRedon 0 and an absent dSubExo print no row.
    assert "Redondeo" not in exonerated
    assert "Subtotal exonerado" not in rounding


_LONGEST_AMOUNT = "999999999999999.99999999"  # tMontoBase: 15 + 8 digits


def test_a_long_amount_continues_on_the_next_line_and_is_never_cut(monkeypatch):
    document = _document_for_scenario("factura_b2b_iva10", "factura")
    signed_xml = re.sub(
        r"<dPUniProSer>[^<]*</dPUniProSer>",
        f"<dPUniProSer>{_LONGEST_AMOUNT}</dPUniProSer>",
        document.signed_xml,
        count=1,
    )
    signed_xml = re.sub(
        r"<dTotIVA>[^<]*</dTotIVA>", f"<dTotIVA>{_LONGEST_AMOUNT}</dTotIVA>", signed_xml
    )

    texts = _drawn_texts(monkeypatch, _with_signed_xml(document, signed_xml))

    # The 22 mm unit price column: integer part, then the decimals.
    start = texts.index("999.999.999.999.999")
    assert texts[start + 1] == ",99999999"
    # The totals column is wide enough for the longest literal in one line.
    assert _printed_after(texts, "Total IVA") == "999.999.999.999.999,99999999"


def test_kude_prints_quantity_and_exchange_rate_with_their_decimals(monkeypatch):
    document = _document_for_scenario("factura_moneda_usd", "factura")
    signed_xml = re.sub(
        r"<dCantProSer>[^<]*</dCantProSer>",
        "<dCantProSer>1234.5</dCantProSer>",
        document.signed_xml,
        count=1,
    )

    texts = _drawn_texts(monkeypatch, _with_signed_xml(document, signed_xml))

    assert "1.234,5" in texts
    rate = ET.fromstring(signed_xml).findtext(
        f"{{{_SIFEN_NS}}}DE/{{{_SIFEN_NS}}}gDatGralOpe/{{{_SIFEN_NS}}}gOpeCom"
        f"/{{{_SIFEN_NS}}}dTiCam"
    )
    assert _undo_separators(_printed_after(texts, "T. cambio")) == rate


def test_foreign_currency_xml_without_f023_prints_no_total_in_guaranies(
    monkeypatch,
):
    document = _document_for_scenario("factura_moneda_usd", "factura")
    signed_xml = re.sub(r"<dTotalGs>[^<]*</dTotalGs>", "", document.signed_xml)

    texts = _drawn_texts(monkeypatch, _with_signed_xml(document, signed_xml))

    assert "TOTAL USD" in texts
    assert "TOTAL EN GUARANÍES" not in texts


def test_kude_prints_the_stamping_start_date_as_dd_mm_aaaa(monkeypatch):
    texts = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_b2b_iva10", "factura")
    )

    # dFeIniT is 2024-03-11 in the XML (NT 10 §1.11).
    assert texts[texts.index("Inicio vigencia") + 1] == "11-03-2024"
    assert "2024-03-11" not in texts


def test_kude_prints_the_stamping_end_date_as_in_the_xml(monkeypatch):
    # NT 10 §1.11 only changes C008; C009 keeps its XML text (MT v150 p. 64).
    document = _document_for_scenario("factura_b2b_iva10", "factura")
    signed_xml = document.signed_xml.replace(
        "</dFeIniT>", "</dFeIniT><dFeFinT>2026-12-31</dFeFinT>", 1
    )

    texts = _drawn_texts(monkeypatch, _with_signed_xml(document, signed_xml))

    assert _printed_after(texts, "Fin vigencia") == "2026-12-31"


def test_kude_data_keeps_the_xml_literals_and_separates_f014_from_f023():
    usd = extract_kude_data(
        document=_document_for_scenario("factura_moneda_usd", "factura"),
        emitter=_emitter(),
    )["kude"]
    pyg = extract_kude_data(
        document=_document_for_scenario("factura_b2b_iva10", "factura"),
        emitter=_emitter(),
    )["kude"]

    assert usd["totales"]["total_general_operacion"] == "120.5"
    assert usd["totales"]["total_general_guaranies"] == "879650"
    assert usd["totales"]["total_iva"] == "10.95454546"
    assert pyg["totales"]["total_general_operacion"] == "100000"
    assert pyg["totales"]["total_general_guaranies"] == "100000"
    assert pyg["totales"]["liquidacion_iva_10"] == "9090.90909091"
    assert pyg["timbrado"]["fecha_inicio_vigencia"] == "2024-03-11"


def test_kude_data_carries_the_exonerated_subtotal_rounding_and_commission():
    rounding = extract_kude_data(
        document=_document_for_scenario("factura_redondeo_50", "factura"),
        emitter=_emitter(),
    )["kude"]["totales"]
    exonerated = extract_kude_data(
        document=_document_for_scenario("factura_iva_parcial_exonerado", "factura"),
        emitter=_emitter(),
    )["kude"]["totales"]

    assert rounding["redondeo"] == "37"
    assert rounding["subtotal_exonerado"] is None
    assert rounding["comision"] is None
    assert exonerated["subtotal_exonerado"] == "15000"
    assert exonerated["redondeo"] == "0"
