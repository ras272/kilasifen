"""Regression tests for CommonMixin XML parser/serializer reuse."""

import importlib
import os

import pytest
from xsdata.formats.dataclass.parsers import XmlParser as RealXmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer as RealXmlSerializer


SAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "kilasifen", "engine", "de", "samples", "v150"
)


@pytest.fixture
def factura_path():
    return os.path.join(SAMPLES_DIR, "factura_electronica.xml")


def test_common_mixin_reuses_parser_instances(monkeypatch, factura_path):
    """CommonMixin should reuse a single parser instance across calls."""

    common_mixin_module = importlib.import_module("kilasifen.engine.CommonMixin")
    parser_inits = []
    common_mixin_module._get_xml_parser.cache_clear()

    class CountingXmlParser(RealXmlParser):
        def __init__(self, *args, **kwargs):
            parser_inits.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(common_mixin_module, "XmlParser", CountingXmlParser)

    from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

    rde_from_path = RDe.from_path(factura_path)
    with open(factura_path, encoding="utf-8") as handler:
        rde_from_xml = RDe.from_xml(handler.read())

    assert rde_from_path.DE.gTimb.iTiDE == "1"
    assert rde_from_xml.DE.gTimb.iTiDE == "1"
    assert len(parser_inits) == 1
    common_mixin_module._get_xml_parser.cache_clear()


def test_common_mixin_reuses_serializer_instances(monkeypatch, factura_path):
    """CommonMixin should reuse serializer instances per pretty-print mode."""

    common_mixin_module = importlib.import_module("kilasifen.engine.CommonMixin")
    serializer_inits = []
    common_mixin_module._get_xml_serializer.cache_clear()

    class CountingXmlSerializer(RealXmlSerializer):
        def __init__(self, *args, **kwargs):
            serializer_inits.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(common_mixin_module, "XmlSerializer", CountingXmlSerializer)

    from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

    rde = RDe.from_path(factura_path)
    pretty_first = rde.to_xml(pretty_print=True)
    pretty_second = rde.to_xml(pretty_print=True)
    compact_first = rde.to_xml(pretty_print=False)
    compact_second = rde.to_xml(pretty_print=False)

    assert pretty_first == pretty_second
    assert compact_first == compact_second
    assert pretty_first != compact_first
    assert len(serializer_inits) == 2
    common_mixin_module._get_xml_serializer.cache_clear()
