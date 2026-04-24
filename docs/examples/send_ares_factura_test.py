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

from pysifen import TEST
from pysifen.assinatura import sign_xml
from pysifen.sdk.fiscal import build_qr_payload, calculate_mod11_dv, generate_cdc
from pysifen.transmissao.de import TransmissaoDE

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


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
    fecha_inicio_timbrado: str,
    codigo_seguridad: str,
) -> bytes:
    cdc = generate_cdc(
        i_tide=1,
        d_ruc_em="80024135",
        d_dv_emi=5,
        d_est="001",
        d_pun_exp="001",
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
    _el(gtimb, "dNumTim", "80024135")
    _el(gtimb, "dEst", "001")
    _el(gtimb, "dPunExp", "001")
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
    _el(act, "cActEco", "47111")
    _el(act, "dDesActEco", "COMERCIO AL POR MENOR")

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
    _el(gcamfe, "dDesIndPres", "Operacion presencial")
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
    _el(item, "dCantProSer", "1")
    valor = _el(item, "gValorItem")
    _el(valor, "dPUniProSer", "110000")
    _el(valor, "dTiCamIt", "1")
    _el(valor, "dTotBruOpeItem", "110000")
    resta = _el(valor, "gValorRestaItem")
    _el(resta, "dDescItem", "0")
    _el(resta, "dDescGloItem", "0")
    _el(resta, "dAntPreUniIt", "0")
    _el(resta, "dAntGloPreUniIt", "0")
    _el(resta, "dTotOpeItem", "110000")
    _el(resta, "dTotOpeGs", "110000")
    iva = _el(item, "gCamIVA")
    _el(iva, "iAfecIVA", "1")
    _el(iva, "dDesAfecIVA", "Gravado IVA")
    _el(iva, "dPropIVA", "100")
    _el(iva, "dTasaIVA", "10")
    _el(iva, "dBasGravIVA", "100000")
    _el(iva, "dLiqIVAItem", "10000")
    _el(iva, "dBasExe", "0")

    tot = _el(de, "gTotSub")
    _el(tot, "dSub10", "110000")
    _el(tot, "dTotOpe", "110000")
    _el(tot, "dTotDesc", "0")
    _el(tot, "dTotDescGlotem", "0")
    _el(tot, "dTotAntItem", "0")
    _el(tot, "dTotAnt", "0")
    _el(tot, "dPorcDescTotal", "0")
    _el(tot, "dDescTotal", "0")
    _el(tot, "dAnticipo", "0")
    _el(tot, "dRedon", "0")
    _el(tot, "dTotGralOpe", "110000")
    _el(tot, "dIVA10", "10000")
    _el(tot, "dTotIVA", "10000")
    _el(tot, "dBaseGrav10", "100000")
    _el(tot, "dTBasGraIVA", "100000")
    _el(tot, "dTotalGs", "110000")

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
    digest = root.find(f".//{{{DS_NS}}}DigestValue")
    if digest is None or not digest.text:
        raise RuntimeError("No DigestValue found in signed XML")
    qr = build_qr_payload(
        cdc=cdc,
        d_fe_emi_de=fecha_emision,
        digest_value=digest.text,
        id_csc=id_csc,
        csc=csc,
        d_ruc_rec="80069563",
        d_tot_gral_ope="110000",
        d_tot_iva="10000",
        c_items=1,
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
    fecha_inicio_timbrado: str,
    codigo_seguridad: str,
    id_csc: str,
    csc: str,
) -> bytes:
    unsigned = build_unsigned_de_base(
        numero_documento=numero_documento,
        fecha_emision=fecha_emision,
        fecha_inicio_timbrado=fecha_inicio_timbrado,
        codigo_seguridad=codigo_seguridad,
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
    parser.add_argument("--fecha-inicio-timbrado", default="2025-07-07")
    parser.add_argument("--codigo-seguridad", default="123456789")
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
        fecha_inicio_timbrado=args.fecha_inicio_timbrado,
        codigo_seguridad=args.codigo_seguridad,
        id_csc=args.id_csc,
        csc=args.csc,
    )
    print(xml.decode("utf-8")[:500])
    print("xml_size:", len(xml))
    if args.send:
        client = TransmissaoDE(
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
