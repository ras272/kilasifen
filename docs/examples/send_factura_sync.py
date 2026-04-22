"""Executable example: send a single DE synchronously."""
from __future__ import annotations

import argparse
from pathlib import Path

from pysifen import TEST
from pysifen.de.bindings.v150.fe_v141 import RDe
from pysifen.sdk.client import SifenClient


def send_factura_sync(
    xml_path: str,
    pfx_path: str,
    pfx_password: str,
    ambiente: int = TEST,
):
    """Load one DE from XML and send it to SIFEN."""
    rde = RDe.from_path(xml_path)
    cert_data = Path(pfx_path).read_bytes()

    with SifenClient(
        ambiente=ambiente,
        pkcs12_data=cert_data,
        pkcs12_password=pfx_password,
    ) as client:
        return client.enviar_de(rde, sign=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send one DE XML to SIFEN (sync)."
    )
    parser.add_argument(
        "--xml",
        required=True,
        help="Path to DE XML file.",
    )
    parser.add_argument(
        "--pfx",
        required=True,
        help="Path to PKCS12 certificate (.pfx).",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="PKCS12 password.",
    )
    parser.add_argument(
        "--ambiente",
        type=int,
        default=TEST,
        help="SIFEN environment (TEST=2, PRODUCCION=1).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = send_factura_sync(
        xml_path=args.xml,
        pfx_path=args.pfx,
        pfx_password=args.password,
        ambiente=args.ambiente,
    )

    prot = getattr(result, "rProtDe", None)
    if prot is not None:
        status = getattr(prot, "dEstRes", None)
        auth = getattr(prot, "dProtAut", None)
        print(f"status={status} protocol={auth}")
    else:
        print("sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
