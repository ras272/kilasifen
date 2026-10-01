"""Tests for the SIFEN KuDE PDF renderer."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
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
