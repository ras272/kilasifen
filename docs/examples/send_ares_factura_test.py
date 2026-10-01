"""Build and send a real ARES factura XML to SIFEN TEST.

This script is intentionally TEST-only. It builds a v150-like DE as raw XML
because current generated FE bindings still miss some DE_v150 fields required
by SIFEN, such as dSisFact and updated item/total structures.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from lxml import etree

from kilasifen.engine import TEST
from kilasifen.engine.firma import sign_xml
from kilasifen.engine.sdk.fiscal import (
    build_qr_payload_from_signed_xml,
    calculate_mod11_dv,
    generate_cdc,
)
from kilasifen.engine.transmision.de import TransmisionDE

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
TOTAL_OPERACION = "110000"
TOTAL_IVA = "10000"
BASE_GRAVADA = "100000"
TOTAL_CANTIDAD = "1"


def _el(parent, name: str, text=None):
    child = etree.SubElement(parent, f"{{{SIFEN_NS}}}{name}")
    if text is not None:
        child.text = str(text)
    return child


def _decimal(value: int | str) -> str:
    return str(value)


def build_unsigned_de_base(
    *,
    numero_documento: str,
    fecha_emision: str,
    timbrado: str,
    fecha_inicio_timbrado: str,
    codigo_seguridad: str,
    establecimiento: str = "001",
    punto_expedicion: str = "001",
    codigo_actividad: str = "82999",
    descripcion_actividad: str = "OTRAS ACTIVIDADES DE SERVICIOS DE APOYO A EMPRESAS N.C.P.",
) -> bytes:
    cdc = generate_cdc(
        i_tide=1,
        d_ruc_em="80024135",
        d_dv_emi=5,
        d_est=establecimiento,
        d_pun_exp=punto_expedicion,
        d_num_doc=numero_documento,
        i_tip_cont=2,
        d_fe_emi_de=fecha_emision,
        i_tip_emi=1,
        d_cod_seg=codigo_seguridad,
    )
    root = etree.Element(
        f"{{{SIFEN_NS}}}rDE",
        nsmap={None: SIFEN_NS, "xsi": XSI_NS},
    )
    root.set(
        f"{{{XSI_NS}}}schemaLocation",
        f"{SIFEN_NS} siRecepDE_v150.xsd",
    )
    _el(root, "dVerFor", "150")

    de = _el(root, "DE")
    de.set("Id", cdc)
    _el(de, "dDVId", calculate_mod11_dv(cdc[:-1]))
    _el(de, "dFecFirma", fecha_emision)
    _el(de, "dSisFact", "1")

    gope = _el(de, "gOpeDE")
    _el(gope, "iTipEmi", "1")
    _el(gope, "dDesTipEmi", "Normal")
    _el(gope, "dCodSeg", codigo_seguridad.zfill(9))

    gtimb = _el(de, "gTimb")
    _el(gtimb, "iTiDE", "1")
    _el(gtimb, "dDesTiDE", "Factura electrónica")
    _el(gtimb, "dNumTim", timbrado)
    _el(gtimb, "dEst", establecimiento)
    _el(gtimb, "dPunExp", punto_expedicion)
    _el(gtimb, "dNumDoc", numero_documento.zfill(7))
    _el(gtimb, "dFeIniT", fecha_inicio_timbrado)

    gdat = _el(de, "gDatGralOpe")
    _el(gdat, "dFeEmiDE", fecha_emision)
    gopecom = _el(gdat, "gOpeCom")
    _el(gopecom, "iTipTra", "1")
    _el(gopecom, "dDesTipTra", "Venta de mercadería")
    _el(gopecom, "iTImp", "1")
    _el(gopecom, "dDesTImp", "IVA")
    _el(gopecom, "cMoneOpe", "PYG")
    _el(gopecom, "dDesMoneOpe", "Guarani")

    gemis = _el(gdat, "gEmis")
    _el(gemis, "dRucEm", "80024135")
    _el(gemis, "dDVEmi", "5")
    _el(gemis, "iTipCont", "2")
    _el(gemis, "dNomEmi", "ARES PARAGUAY SRL")
    _el(gemis, "dDirEmi", "ASUNCION")
    _el(gemis, "dNumCas", "0")
    _el(gemis, "cDepEmi", "1")
    _el(gemis, "dDesDepEmi", "CAPITAL")
    _el(gemis, "cCiuEmi", "1")
    _el(gemis, "dDesCiuEmi", "ASUNCION (DISTRITO)")
    _el(gemis, "dTelEmi", "021000000")
    _el(gemis, "dEmailE", "teresa@ares.com.py")
    act = _el(gemis, "gActEco")
    _el(act, "cActEco", codigo_actividad)
    _el(act, "dDesActEco", descripcion_actividad)

    grec = _el(gdat, "gDatRec")
    _el(grec, "iNatRec", "1")
    _el(grec, "iTiOpe", "1")
    _el(grec, "cPaisRec", "PRY")
    _el(grec, "dDesPaisRe", "Paraguay")
    _el(grec, "iTiContRec", "2")
    _el(grec, "dRucRec", "80069563")
    _el(grec, "dDVRec", "1")
    _el(grec, "dNomRec", "TIPS S.A")

    gdtip = _el(de, "gDtipDE")
    gcamfe = _el(gdtip, "gCamFE")
    _el(gcamfe, "iIndPres", "1")
    _el(gcamfe, "dDesIndPres", "Operación presencial")
    gcond = _el(gdtip, "gCamCond")
    _el(gcond, "iCondOpe", "1")
    _el(gcond, "dDCondOpe", "Contado")
    pago = _el(gcond, "gPaConEIni")
    _el(pago, "iTiPago", "1")
    _el(pago, "dDesTiPag", "Efectivo")
    _el(pago, "dMonTiPag", "110000")
    _el(pago, "cMoneTiPag", "PYG")
    _el(pago, "dDMoneTiPag", "Guarani")

    item = _el(gdtip, "gCamItem")
    _el(item, "dCodInt", "TEST001")
    _el(item, "dDesProSer", "Producto de prueba TEST")
    _el(item, "cUniMed", "77")
    _el(item, "dDesUniMed", "UNI")
    _el(item, "dCantProSer", TOTAL_CANTIDAD)
    valor = _el(item, "gValorItem")
    _el(valor, "dPUniProSer", TOTAL_OPERACION)
    _el(valor, "dTotBruOpeItem", TOTAL_OPERACION)
    resta = _el(valor, "gValorRestaItem")
    _el(resta, "dDescItem", "0")
    _el(resta, "dPorcDesIt", "0.00")
    _el(resta, "dAntPreUniIt", "0")
    _el(resta, "dAntGloPreUniIt", "0")
    _el(resta, "dTotOpeItem", TOTAL_OPERACION)
    iva = _el(item, "gCamIVA")
    _el(iva, "iAfecIVA", "1")
    _el(iva, "dDesAfecIVA", "Gravado IVA")
    _el(iva, "dPropIVA", "100")
    _el(iva, "dTasaIVA", "10")
    _el(iva, "dBasGravIVA", BASE_GRAVADA)
    _el(iva, "dLiqIVAItem", TOTAL_IVA)
    _el(iva, "dBasExe", "0")

    tot = _el(de, "gTotSub")
    _el(tot, "dSubExe", "0")
    _el(tot, "dSubExo", "0")
    _el(tot, "dSub5", "0")
    _el(tot, "dSub10", TOTAL_OPERACION)
    _el(tot, "dTotOpe", TOTAL_OPERACION)
    _el(tot, "dTotDesc", "0")
    _el(tot, "dTotDescGlotem", "0")
    _el(tot, "dTotAntItem", "0")
    _el(tot, "dTotAnt", "0")
    _el(tot, "dPorcDescTotal", "0.00")
    _el(tot, "dDescTotal", "0")
    _el(tot, "dAnticipo", "0")
    _el(tot, "dRedon", "0")
    _el(tot, "dComi", "0")
    _el(tot, "dTotGralOpe", TOTAL_OPERACION)
    _el(tot, "dIVA5", "0")
    _el(tot, "dIVA10", TOTAL_IVA)
    _el(tot, "dLiqTotIVA5", "0")
    _el(tot, "dLiqTotIVA10", "0")
    _el(tot, "dIVAComi", "0")
    _el(tot, "dTotIVA", TOTAL_IVA)
    _el(tot, "dBaseGrav5", "0")
    _el(tot, "dBaseGrav10", BASE_GRAVADA)
    _el(tot, "dTBasGraIVA", BASE_GRAVADA)

    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def finalize_signed_de_with_qr(
    signed_xml: str,
    *,
    cdc: str,
    fecha_emision: str,
    id_csc: str,
    csc: str,
) -> bytes:
    root = etree.fromstring(signed_xml.encode("utf-8"))
    qr = build_qr_payload_from_signed_xml(
        signed_xml=signed_xml,
        id_csc=id_csc,
        csc=csc,
        environment="test",
    )
    gcam = etree.Element(f"{{{SIFEN_NS}}}gCamFuFD")
    dcar = etree.SubElement(gcam, f"{{{SIFEN_NS}}}dCarQR")
    dcar.text = qr["url"]
    root.append(gcam)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def build_signed_ares_de_xml(
    *,
    cert_data: bytes,
    password: str,
    numero_documento: str,
    fecha_emision: str,
    timbrado: str,
    fecha_inicio_timbrado: str,
    codigo_seguridad: str,
    establecimiento: str,
    punto_expedicion: str,
    codigo_actividad: str,
    descripcion_actividad: str,
    id_csc: str,
    csc: str,
) -> bytes:
    unsigned = build_unsigned_de_base(
        numero_documento=numero_documento,
        fecha_emision=fecha_emision,
        timbrado=timbrado,
        fecha_inicio_timbrado=fecha_inicio_timbrado,
        codigo_seguridad=codigo_seguridad,
        establecimiento=establecimiento,
        punto_expedicion=punto_expedicion,
        codigo_actividad=codigo_actividad,
        descripcion_actividad=descripcion_actividad,
    )
    root = etree.fromstring(unsigned)
    cdc = root.find(f"{{{SIFEN_NS}}}DE").get("Id")
    signed = sign_xml(unsigned, cert_data, password, cdc)
    return finalize_signed_de_with_qr(
        signed,
        cdc=cdc,
        fecha_emision=fecha_emision,
        id_csc=id_csc,
        csc=csc,
    )


def _load_cert() -> tuple[bytes, str]:
    pfx_path = os.environ.get("SIFEN_PFX_PATH")
    password = os.environ.get("SIFEN_PFX_PASS")
    if not pfx_path or not password:
        raise RuntimeError("Defina SIFEN_PFX_PATH y SIFEN_PFX_PASS")
    return Path(pfx_path).read_bytes(), password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build/send ARES factura electronica to SIFEN TEST."
    )
    parser.add_argument("--numero-documento", default="0000001")
    parser.add_argument("--fecha-emision", default="2026-04-24T12:00:00")
    parser.add_argument("--timbrado", default="80024135")
    parser.add_argument("--fecha-inicio-timbrado", default="2025-07-07")
    parser.add_argument("--codigo-seguridad", default="123456789")
    parser.add_argument("--establecimiento", default="001")
    parser.add_argument("--punto-expedicion", default="001")
    parser.add_argument("--codigo-actividad", default="82999")
    parser.add_argument(
        "--descripcion-actividad",
        default="OTRAS ACTIVIDADES DE SERVICIOS DE APOYO A EMPRESAS N.C.P.",
    )
    parser.add_argument("--id-csc", default="0001")
    parser.add_argument("--csc", default="ABCD0000000000000000000000000000")
    parser.add_argument("--send", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cert_data, password = _load_cert()
    xml = build_signed_ares_de_xml(
        cert_data=cert_data,
        password=password,
        numero_documento=args.numero_documento,
        fecha_emision=args.fecha_emision,
        timbrado=args.timbrado,
        fecha_inicio_timbrado=args.fecha_inicio_timbrado,
        codigo_seguridad=args.codigo_seguridad,
        establecimiento=args.establecimiento,
        punto_expedicion=args.punto_expedicion,
        codigo_actividad=args.codigo_actividad,
        descripcion_actividad=args.descripcion_actividad,
        id_csc=args.id_csc,
        csc=args.csc,
    )
    print(xml.decode("utf-8")[:500])
    print("xml_size:", len(xml))
    if args.send:
        client = TransmisionDE(
            ambiente=TEST,
            pkcs12_data=cert_data,
            pkcs12_password=password,
            max_retries=0,
        )
        result = client.enviar_de_xml(xml)
        print("estado:", result.rProtDe.dEstRes)
        for item in result.rProtDe.gResProc:
            print(item.dCodRes, item.dMsgRes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
