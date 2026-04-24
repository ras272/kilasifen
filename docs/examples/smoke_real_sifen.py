"""Smoke test real contra SIFEN TEST con certificado PKCS12.

Uso recomendado:
    python docs/examples/smoke_real_sifen.py --ruc 80024135-5

El envio de DE esta desactivado por defecto para evitar consumir numeracion
accidentalmente. Usar --send-de solo con XML preparado para TEST.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from lxml import etree

from pysifen import TEST
from pysifen.assinatura import sign_xml
from pysifen.de.bindings.v150.fe_v141 import RDe
from pysifen.sdk.client import SifenClient
from pysifen.sdk.fiscal import build_qr_payload, generate_cdc


def _read_secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Defina la variable de entorno {name}")
    return value


def _load_cert() -> tuple[bytes, str]:
    pfx_path = Path(_read_secret("SIFEN_PFX_PATH"))
    password = _read_secret("SIFEN_PFX_PASS")
    return pfx_path.read_bytes(), password


def _digest_from_signed_xml(signed_xml: str) -> str:
    root = etree.fromstring(signed_xml.encode())
    ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
    digest = root.find(".//ds:DigestValue", ns)
    if digest is None or not digest.text:
        raise RuntimeError("No se encontro DigestValue en XML firmado")
    return digest.text


def run_smoke(args: argparse.Namespace) -> int:
    cert_data, password = _load_cert()
    sample_path = Path(args.xml)
    rde = RDe.from_path(sample_path)

    with SifenClient(
        ambiente=TEST,
        pkcs12_data=cert_data,
        pkcs12_password=password,
        timeout=args.timeout,
        max_retries=0,
    ) as client:
        ruc_result = client.consultar_ruc(args.ruc)
        print("consulta_ruc:", ruc_result.dCodRes, ruc_result.dMsgRes)
        if ruc_result.xContRUC is not None:
            print("razon_social:", ruc_result.xContRUC.dRazCons.strip())
            print("estado:", ruc_result.xContRUC.dDesEstCons)
            print("facturador_electronico:", ruc_result.xContRUC.dRUCFactElec)

        signed = sign_xml(rde.to_xml(), cert_data, password, rde.DE.Id)
        digest = _digest_from_signed_xml(signed)
        print("firma_local: OK")

        cdc = generate_cdc(
            i_tide=1,
            d_ruc_em=args.emisor_ruc,
            d_dv_emi=args.emisor_dv,
            d_est=args.establecimiento,
            d_pun_exp=args.punto_expedicion,
            d_num_doc=args.numero_documento,
            i_tip_cont=args.tipo_contribuyente,
            d_fe_emi_de=args.fecha_emision,
            i_tip_emi=args.tipo_emision,
            d_cod_seg=args.codigo_seguridad,
        )
        qr = build_qr_payload(
            cdc=cdc,
            d_fe_emi_de=args.fecha_emision,
            digest_value=digest,
            id_csc=args.id_csc,
            csc=args.csc,
            d_ruc_rec=args.receptor_ruc,
            d_tot_gral_ope=args.total_operacion,
            d_tot_iva=args.total_iva,
            c_items=args.items,
            environment="test",
        )
        print("cdc:", cdc)
        print("qr_hash:", qr["c_hash_qr"])
        print("qr_len:", len(qr["url"]))

        if args.send_de:
            result = client.enviar_de(rde, sign=True)
            prot = result.rProtDe
            print("enviar_de:", prot.dEstRes)
            for item in prot.gResProc:
                print(item.dCodRes, item.dMsgRes)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke real contra SIFEN TEST."
    )
    parser.add_argument("--ruc", default="80024135-5")
    parser.add_argument(
        "--xml",
        default="pysifen/de/samples/v150/factura_electronica.xml",
    )
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--send-de", action="store_true")
    parser.add_argument("--emisor-ruc", default="80024135")
    parser.add_argument("--emisor-dv", default="5")
    parser.add_argument("--establecimiento", default="001")
    parser.add_argument("--punto-expedicion", default="001")
    parser.add_argument("--numero-documento", default="1")
    parser.add_argument("--tipo-contribuyente", default="2")
    parser.add_argument("--fecha-emision", default="2026-04-24T12:00:00")
    parser.add_argument("--tipo-emision", default="1")
    parser.add_argument("--codigo-seguridad", default="123456789")
    parser.add_argument("--id-csc", default="0001")
    parser.add_argument("--csc", default="ABCD0000000000000000000000000000")
    parser.add_argument("--receptor-ruc", default="80069563")
    parser.add_argument("--total-operacion", default="100000")
    parser.add_argument("--total-iva", default="9091")
    parser.add_argument("--items", default="1")
    return parser


def main() -> int:
    return run_smoke(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
