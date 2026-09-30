"""Tests for KuDE HTML rendering helpers."""

from pathlib import Path

from kilasifen.engine.de.bindings.v150.fe_v141 import RDe
from kilasifen.engine.sdk.kude import (
    build_kude_context,
    render_kude_html,
    render_kude_html_from_xml,
    save_kude_html,
)

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

    assert ctx["cdc"] == "01800695631001001000000612024112917595714694"
    assert ctx["emisor_nombre"] == "Empresa Demo S.A."
    assert ctx["receptor_nombre"] == "Cliente Demo S.A."
    assert ctx["cantidad_items"] == "2"
    assert ctx["total_operacion"] == "1150000"
    assert len(ctx["items"]) == 2


def test_render_kude_html_contains_main_sections():
    html = render_kude_html(_load_sample_rde(), title="KuDE Factura")

    assert "<!doctype html>" in html
    assert "KuDE Factura" in html
    assert "Detalle de items" in html
    assert "Empresa Demo S.A." in html
    assert "Cliente Demo S.A." in html
    assert "PROD001" in html
    assert "SERV001" in html
    assert "https://ekuatia.set.gov.py/consultas/qr?" in html


def test_render_kude_html_from_xml_string():
    xml = (SAMPLES_DIR / "factura_electronica.xml").read_text(
        encoding="utf-8"
    )
    html = render_kude_html_from_xml(xml)

    assert "KuDE" in html
    assert "80069563-1" in html
    assert "4192083-5" in html


def test_save_kude_html_writes_file(tmp_path):
    out = tmp_path / "kude.html"
    path = save_kude_html(_load_sample_rde(), out, title="KuDE Test")

    assert path == out
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "KuDE Test" in content
    assert "1150000" in content
