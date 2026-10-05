"""Tests for KuDE HTML rendering helpers."""

from pathlib import Path

from kilasifen.engine.de.bindings.v150.fe_v141 import RDe
from kilasifen.engine.sdk.kude import (
    build_kude_context,
    render_kude_html,
    render_kude_html_from_xml,
    save_kude_html,
)
from tests._muestras import FACTURA

SAMPLES_DIR = (
    Path(__file__).resolve().parents[1]
    / "kilasifen"
    / "engine"
    / "de"
    / "samples"
    / "v150"
)


def _load_sample_rde() -> RDe:
    return RDe.from_path(str(SAMPLES_DIR / "factura_electronica.xml"))


def test_build_kude_context_from_sample():
    ctx = build_kude_context(_load_sample_rde())

    assert ctx["cdc"] == FACTURA.cdc
    assert ctx["emisor_nombre"] == FACTURA.nombre_emisor
    assert ctx["receptor_nombre"] == FACTURA.nombre_receptor
    assert ctx["cantidad_items"] == str(FACTURA.cantidad_items)
    assert ctx["total_operacion"] == str(FACTURA.total_general)
    assert len(ctx["items"]) == FACTURA.cantidad_items


def test_render_kude_html_contains_main_sections():
    html = render_kude_html(_load_sample_rde(), title="KuDE Factura")

    assert "<!doctype html>" in html
    assert "KuDE Factura" in html
    assert "Detalle de items" in html
    assert FACTURA.nombre_emisor in html
    assert FACTURA.nombre_receptor in html
    assert FACTURA.codigos_items[0] in html
    assert FACTURA.codigos_items[1] in html
    assert "https://ekuatia.set.gov.py/consultas/qr?" in html


def test_render_kude_html_from_xml_string():
    xml = (SAMPLES_DIR / "factura_electronica.xml").read_text(
        encoding="utf-8"
    )
    html = render_kude_html_from_xml(xml)

    assert "KuDE" in html
    assert f"{FACTURA.ruc_emisor}-{FACTURA.dv_emisor}" in html
    assert f"{FACTURA.ruc_receptor}-{FACTURA.dv_receptor}" in html


def test_save_kude_html_writes_file(tmp_path):
    out = tmp_path / "kude.html"
    path = save_kude_html(_load_sample_rde(), out, title="KuDE Test")

    assert path == out
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "KuDE Test" in content
    assert str(FACTURA.total_general) in content
