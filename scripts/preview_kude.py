"""Generate KuDE PDFs for all golden scenarios for visual review.

Usage: python scripts/preview_kude.py
Output: tmp/kude_previews/<scenario>.pdf
"""

from datetime import datetime, timezone
from pathlib import Path

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.kude.pdf_renderer import render_kude_pdf
from kilasifen.testing.typed_contract_scenarios import get_typed_contract_scenarios

REPO = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO / "tests" / "golden"
OUT_DIR = REPO / "tmp" / "kude_previews"


def make_emitter() -> Emitter:
    ts = datetime.now(timezone.utc)
    return Emitter(
        id="emitter-1",
        external_id="erp-test",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=ts,
        updated_at=ts,
    )


def make_document(name: str, doc_type: str) -> Document:
    signed_xml = (GOLDEN_DIR / f"{name}.xml").read_text(encoding="utf-8")
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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    emitter = make_emitter()
    for scenario in get_typed_contract_scenarios():
        document = make_document(scenario.name, scenario.document_type)
        pdf_bytes = render_kude_pdf(document=document, emitter=emitter)
        out_path = OUT_DIR / f"{scenario.name}.pdf"
        out_path.write_bytes(pdf_bytes)
        print(f"  {scenario.name:32s} -> {out_path.relative_to(REPO)} ({len(pdf_bytes)} bytes)")
    print(f"\nDone. Open {OUT_DIR.relative_to(REPO)} to review.")


if __name__ == "__main__":
    main()
