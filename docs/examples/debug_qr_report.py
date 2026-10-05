"""Generate a local QR/debug report from a signed DE XML."""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from lxml import etree

from kilasifen.engine.sdk.fiscal import build_qr_payload_from_signed_xml

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local QR debug report from a signed DE XML."
    )
    parser.add_argument("--xml", required=True)
    parser.add_argument("--id-csc", required=True)
    parser.add_argument("--csc", required=True)
    parser.add_argument(
        "--environment",
        choices=("test", "production"),
        default="test",
    )
    parser.add_argument("--out", default="debug_qr_report.txt")
    return parser.parse_args()


def _validate_against_schema(xml_bytes: bytes) -> tuple[bool, list[str]]:
    schema_doc = etree.parse("kilasifen/engine/de/schemas/v150/siRecepDE_v150.xsd")
    schema = etree.XMLSchema(schema_doc)
    doc = etree.fromstring(xml_bytes)
    is_valid = schema.validate(doc)
    errors = [f"line {err.line}: {err.message}" for err in schema.error_log]
    return is_valid, errors


def _collect_report(
    xml_bytes: bytes,
    *,
    id_csc: str,
    csc: str,
    environment: str,
) -> str:
    root = etree.fromstring(xml_bytes)
    ns = {"s": SIFEN_NS, "ds": DS_NS}

    built = build_qr_payload_from_signed_xml(
        signed_xml=xml_bytes,
        id_csc=id_csc,
        csc=csc,
        environment=environment,
    )
    de = root.find("s:DE", ns)
    existing_dcarqr = root.findtext("s:gCamFuFD/s:dCarQR", namespaces=ns) or ""
    canonicalization_node = root.find(".//ds:CanonicalizationMethod", ns)
    canonicalization = (
        canonicalization_node.get("Algorithm", "")
        if canonicalization_node is not None
        else ""
    )
    transforms = [
        transform.get("Algorithm", "")
        for transform in root.findall(".//ds:Transform", ns)
    ]
    existing_query = dict(parse_qsl(urlsplit(existing_dcarqr).query))
    built_query = dict(parse_qsl(urlsplit(built["url"]).query))
    schema_valid, schema_errors = _validate_against_schema(xml_bytes)

    lines = [
        "QR Debug Report",
        "===============",
        "",
        f"schema_valid={schema_valid}",
        f"dcarqr_matches_rebuilt={existing_dcarqr == built['url']}",
        f"de_id={de.get('Id') if de is not None else ''}",
        f"dFeEmiDE={root.findtext('s:DE/s:gDatGralOpe/s:dFeEmiDE', namespaces=ns) or ''}",
        f"iNatRec={root.findtext('s:DE/s:gDatGralOpe/s:gDatRec/s:iNatRec', namespaces=ns) or ''}",
        f"dRucRec={root.findtext('s:DE/s:gDatGralOpe/s:gDatRec/s:dRucRec', namespaces=ns) or ''}",
        f"dNumIDRec={root.findtext('s:DE/s:gDatGralOpe/s:gDatRec/s:dNumIDRec', namespaces=ns) or ''}",
        f"dTotGralOpe={root.findtext('s:DE/s:gTotSub/s:dTotGralOpe', namespaces=ns) or ''}",
        f"dTotIVA={root.findtext('s:DE/s:gTotSub/s:dTotIVA', namespaces=ns) or ''}",
        f"cItems={len(root.findall('s:DE/s:gDtipDE/s:gCamItem', ns))}",
        f"digest_value={root.findtext('.//ds:Reference/ds:DigestValue', namespaces=ns) or ''}",
        f"canonicalization={canonicalization}",
        f"transforms={', '.join(transforms)}",
        "",
        "existing_dcarqr",
        "--------------",
        existing_dcarqr,
        "",
        "rebuilt_dcarqr",
        "-------------",
        built["url"],
        "",
        "existing_query_params",
        "-------------------",
    ]

    for key in sorted(existing_query):
        lines.append(f"{key}={existing_query[key]}")

    lines.extend(
        [
            "",
            "rebuilt_query_params",
            "-------------------",
        ]
    )
    for key in sorted(built_query):
        lines.append(f"{key}={built_query[key]}")

    if schema_errors:
        lines.extend(["", "schema_errors", "-------------", *schema_errors])

    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    xml_bytes = Path(args.xml).read_bytes()
    report = _collect_report(
        xml_bytes,
        id_csc=args.id_csc,
        csc=args.csc,
        environment=args.environment,
    )
    Path(args.out).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
