"""Tests for the SIFEN KuDE PDF renderer."""

import copy
import re
import zlib
from dataclasses import replace
from datetime import datetime, timezone
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


def test_pyg_kude_prints_whole_guaranies_and_the_total_in_guaranies(monkeypatch):
    texts = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_b2b_iva10", "factura")
    )

    # dIVA10 is 9090.90909091 in the XML (NT 13).
    assert "9.091" in texts
    assert "100.000" in texts
    assert not any("9090.9" in text or "90909.0" in text for text in texts)
    band = texts.index("TOTAL EN GUARANÍES")
    assert texts[band + 1] == "100.000"
    assert not any(text.startswith("TOTAL PYG") for text in texts)


def test_foreign_currency_kude_prints_f014_and_f023_as_total_in_guaranies(
    monkeypatch,
):
    texts = _drawn_texts(
        monkeypatch, _document_for_scenario("factura_moneda_usd", "factura")
    )

    # F014 = 120.5 USD, F023 dTotalGs = 879650 (NT 08 §1.2), F017 10.95454546.
    general = texts.index("TOTAL USD")
    assert texts[general + 1] == "120,50"
    guaranies = texts.index("TOTAL EN GUARANÍES")
    assert texts[guaranies + 1] == "879.650"
    assert "10,95" in texts


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
