"""XML accepted by the deprecated raw document route, built from the goldens.

The raw route only accepts an unsigned ``rDE`` that validates against the
official XSD, so tests that need a raw document reuse a golden document
without its ``Signature`` instead of inventing toy XML.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

_XMLDSIG_SIGNATURE = "{http://www.w3.org/2000/09/xmldsig#}Signature"
_SIFEN_DE = "{http://ekuatia.set.gov.py/sifen/xsd}DE"


def golden_signed_xml(scenario: str = "factura_b2b_iva10") -> str:
    """Return a golden signed ``rDE`` as text."""

    return (GOLDEN_DIR / f"{scenario}.xml").read_text(encoding="utf-8")


def unsigned_rde(scenario: str = "factura_b2b_iva10") -> tuple[str, str]:
    """Return an XSD-valid unsigned ``rDE`` and the ``Id`` of its ``DE``."""

    root = etree.fromstring(golden_signed_xml(scenario).encode("utf-8"))
    for signature in root.findall(_XMLDSIG_SIGNATURE):
        root.remove(signature)
    de = root.find(_SIFEN_DE)
    assert de is not None
    return etree.tostring(root, encoding="unicode"), de.get("Id")


def raw_document_payload(scenario: str = "factura_b2b_iva10") -> dict[str, str]:
    """Return a raw-route ``payload`` with ``generated_xml`` and ``doc_id``."""

    generated_xml, doc_id = unsigned_rde(scenario)
    return {"generated_xml": generated_xml, "doc_id": doc_id}
