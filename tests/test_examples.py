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
