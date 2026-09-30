"""Executable example: send a DE batch asynchronously."""
from __future__ import annotations

import argparse
from pathlib import Path

from kilasifen.engine import TEST
from kilasifen.engine.de.bindings.v150.fe_v141 import RDe
from kilasifen.engine.sdk.client import SifenClient


def send_lote(
    xml_paths: list[str],
    pfx_path: str,
    pfx_password: str,
    ambiente: int = TEST,
):
    """Load DEs from XML files and send them in one batch."""
    rdes = [RDe.from_path(path) for path in xml_paths]
    cert_data = Path(pfx_path).read_bytes()

    with SifenClient(
        ambiente=ambiente,
        pkcs12_data=cert_data,
        pkcs12_password=pfx_password,
    ) as client:
        return client.enviar_lote(rdes, sign=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send a DE batch to SIFEN (async)."
    )
    parser.add_argument(
        "--xml",
        nargs="+",
        required=True,
        help="One or more DE XML paths (max 50).",
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
    result = send_lote(
        xml_paths=args.xml,
        pfx_path=args.pfx,
        pfx_password=args.password,
        ambiente=args.ambiente,
    )
    protocol = getattr(result, "dProtConsLote", None)
    code = getattr(result, "dCodRes", None)
    print(f"code={code} lote_protocol={protocol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
