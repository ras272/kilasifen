"""Smoke checks for docs/examples scripts."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "docs" / "examples"


@pytest.mark.parametrize(
    "filename",
    [
        "send_factura_sync.py",
        "send_lote.py",
        "smoke_real_sifen.py",
        "send_ares_factura_test.py",
    ],
)
def test_example_script_importable(filename: str):
    path = EXAMPLES_DIR / filename
    spec = importlib.util.spec_from_file_location(
        f"docs_examples_{path.stem}",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
    assert hasattr(module, "build_parser")


def test_raw_route_example_sends_xml_the_raw_policy_accepts():
    from kilasifen.infrastructure.sifen.raw_xml_policy import (
        validate_raw_document_payload,
    )
    from tests._raw_xml import unsigned_rde

    path = EXAMPLES_DIR / "kila_api_emit_document.py"
    spec = importlib.util.spec_from_file_location("docs_examples_raw_route", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rde_xml, _doc_id = unsigned_rde()

    body = module.build_request_body(
        rde_xml=rde_xml,
        external_id="erp-raw-example",
        idempotency_key="erp-raw-example",
    )

    validate_raw_document_payload(body["payload"])
