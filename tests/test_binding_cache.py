"""Reutilizacion del parser y los serializadores de xsdata en BindingMixin."""

from pathlib import Path

import pytest
from xsdata.formats.dataclass.parsers import XmlParser as XmlParserReal
from xsdata.formats.dataclass.serializers import XmlSerializer as XmlSerializerReal

from kilasifen.engine import binding

REPO = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO / "kilasifen" / "engine" / "de" / "samples" / "v150"


@pytest.fixture
def factura_path() -> Path:
    return SAMPLES_DIR / "factura_electronica.xml"


@pytest.fixture
def caches_limpios():
    binding._parser_compartido.cache_clear()
    binding._serializador_compartido.cache_clear()
    yield
    binding._parser_compartido.cache_clear()
    binding._serializador_compartido.cache_clear()


def test_reutiliza_un_unico_parser(monkeypatch, factura_path, caches_limpios):
    creados = []

    class XmlParserContado(XmlParserReal):
        def __init__(self, *args, **kwargs):
            creados.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(binding, "XmlParser", XmlParserContado)

    from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

    desde_archivo = RDe.from_path(factura_path)
    desde_texto = RDe.from_xml(factura_path.read_text(encoding="utf-8"))

    assert desde_archivo.DE.gTimb.iTiDE == "1"
    assert desde_texto.DE.gTimb.iTiDE == "1"
    assert len(creados) == 1


def test_reutiliza_un_serializador_por_modo(monkeypatch, factura_path, caches_limpios):
    creados = []

    class XmlSerializerContado(XmlSerializerReal):
        def __init__(self, *args, **kwargs):
            creados.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(binding, "XmlSerializer", XmlSerializerContado)

    from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

    rde = RDe.from_path(factura_path)
    con_sangria = [rde.to_xml(pretty_print=True) for _ in range(2)]
    compacto = [rde.to_xml(pretty_print=False) for _ in range(2)]

    assert con_sangria[0] == con_sangria[1]
    assert compacto[0] == compacto[1]
    assert con_sangria[0] != compacto[0]
    assert len(creados) == 2
