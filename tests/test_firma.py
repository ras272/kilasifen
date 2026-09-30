"""Tests del modulo de firma y de las utilidades de BindingMixin."""
from __future__ import annotations

from pathlib import Path

import pytest

from kilasifen.engine import binding, firma

CERT_PATH = Path(__file__).resolve().parent / "test_cert.pfx"
CERT_PASSWORD = "test1234"
XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"


def test_sign_xml_explains_missing_sign_extra(monkeypatch):
    real_find_spec = firma.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "signxml":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(firma, "find_spec", fake_find_spec)

    with pytest.raises(ImportError, match=r'pip install "kilasifen\[sign\]"'):
        firma.sign_xml("<a/>", b"", "", "x")


def test_sign_xml_places_signature_after_signed_node():
    pytest.importorskip("signxml")
    from lxml import etree

    xml = '<raiz><nodo Id="abc123"><v>1</v></nodo></raiz>'
    signed = firma.sign_xml(xml, CERT_PATH.read_bytes(), CERT_PASSWORD, "abc123")

    root = etree.fromstring(signed.encode("utf-8"))
    hijos = [etree.QName(hijo).localname for hijo in root]
    assert hijos == ["nodo", "Signature"]
    referencia = root.find(f".//{{{XMLDSIG_NS}}}Reference")
    assert referencia is not None
    assert referencia.get("URI") == "#abc123"


def test_engine_facade_exposes_firma_sign_xml():
    import kilasifen.engine as engine

    assert engine.sign_xml is firma.sign_xml


@pytest.mark.parametrize(
    ("modulo", "esperado"),
    [
        ("kilasifen.engine.de.bindings.v150.fe_v141", ("de", "v150")),
        ("kilasifen.engine.otra.bindings.v200.algo", ("otra", "v200")),
        ("tests.test_validation_registry", ("de", "v150")),
        ("bindings", ("de", "v150")),
    ],
)
def test_binding_mixin_deduce_familia_y_version(modulo, esperado):
    assert binding._familia_y_version(modulo) == esperado
