from __future__ import annotations

import importlib.util
from pathlib import Path

from lxml import etree

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "examples"
    / "send_ares_factura_test.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "send_ares_factura_test",
        EXAMPLE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_unsigned_de_base_has_required_v150_fields():
    module = _load_module()

    xml = module.build_unsigned_de_base(
        numero_documento="0000001",
        fecha_emision="2026-04-24T12:00:00",
        timbrado="17094237",
        fecha_inicio_timbrado="2025-07-07",
        codigo_seguridad="123456789",
        codigo_actividad="82999",
        descripcion_actividad="OTRAS ACTIVIDADES DE SERVICIOS DE APOYO A EMPRESAS N.C.P.",
    )
    root = etree.fromstring(xml)
    ns = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}

    assert root.find("s:DE/s:dSisFact", ns).text == "1"
    assert root.find("s:DE/s:gTimb/s:dNumTim", ns).text == "17094237"
    assert root.find("s:DE/s:gDatGralOpe/s:gEmis/s:gActEco/s:cActEco", ns).text == "82999"
    assert root.find("s:DE/s:gDtipDE/s:gCamFE/s:dDesIndPres", ns).text == "Operación presencial"
    assert root.find("s:DE/s:gDatGralOpe/s:gDatRec/s:iTiContRec", ns).text == "2"
    assert root.find(".//s:gCamIVA/s:dBasExe", ns).text == "0"
    assert root.find(".//s:gValorItem/s:dTiCamIt", ns) is None
    assert root.find(".//s:gValorRestaItem/s:dTotOpeGs", ns) is None
    assert root.find(".//s:gTotSub/s:dTotalGs", ns) is None
    assert root.find(".//s:gTotSub/s:dTotGralOpe", ns).text == "110000"
    assert root.find(".//s:gTotSub/s:dTotIVA", ns).text == "10000"
    assert root.find(".//s:gTotSub/s:dTotDescGlotem", ns).text == "0"
    assert root.find(".//s:gTotSub/s:dComi", ns).text == "0"
    assert root.find(".//s:gValorRestaItem/s:dPorcDesIt", ns).text == "0.00"
    assert root.find("s:gCamFuFD", ns) is None


def test_finalize_signed_de_places_signature_before_qr():
    module = _load_module()
    ns = "http://ekuatia.set.gov.py/sifen/xsd"
    ds = "http://www.w3.org/2000/09/xmldsig#"
    cdc = "01800241355001001000000122026042411234567899"
    signed = (
        f'<rDE xmlns="{ns}"><dVerFor>150</dVerFor><DE Id="{cdc}">'
        "<gTimb><iTiDE>1</iTiDE></gTimb>"
        "<gDatGralOpe><dFeEmiDE>2026-04-24T12:00:00</dFeEmiDE>"
        "<gOpeCom><iTImp>1</iTImp></gOpeCom>"
        "<gDatRec><iNatRec>1</iNatRec><dRucRec>80069563</dRucRec></gDatRec>"
        "</gDatGralOpe>"
        "<gDtipDE><gCamItem/></gDtipDE>"
        "<gTotSub><dTotGralOpe>110000.00000000</dTotGralOpe>"
        "<dTotIVA>10000.00000000</dTotIVA></gTotSub>"
        "</DE>"
        f'<Signature xmlns="{ds}"><SignedInfo><Reference>'
        "<DigestValue>abc123=</DigestValue></Reference></SignedInfo>"
        "</Signature></rDE>"
    )

    final_xml = module.finalize_signed_de_with_qr(
        signed,
        cdc=cdc,
        fecha_emision="2026-04-24T12:00:00",
        id_csc="0001",
        csc="ABCD0000000000000000000000000000",
    )
    root = etree.fromstring(final_xml)

    child_names = [etree.QName(child).localname for child in root]
    assert child_names == ["dVerFor", "DE", "Signature", "gCamFuFD"]
    dcarqr = root.find(f"{{{ns}}}gCamFuFD/{{{ns}}}dCarQR").text
    assert dcarqr.startswith("https://ekuatia.set.gov.py/consultas-test/qr?")
