"""Write the real SIFEN QR into a signed DE XML.

``gCamFuFD/dCarQR`` sits outside the signed ``<DE>``, so its text can be
replaced after signing without invalidating the signature. The URL comes
from :func:`kilasifen.engine.sdk.fiscal.build_qr_payload_from_signed_xml`,
the only QR implementation of the project: it reads the literal values of
the signed XML, including the real ``DigestValue`` (MT v150 §13.8; NT 10
§3-4; NT 23 §1.1). The replacement is textual so the signer's exact byte
serialization is kept.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from kilasifen.domain.emitters.models import Emitter
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.fiscal import build_qr_payload_from_signed_xml

_DCARQR_PATTERN = re.compile(r"<dCarQR>([^<]*)</dCarQR>")


def apply_real_qr_to_signed_xml(signed_xml: str, *, emitter: Emitter) -> str:
    """Replace the ``dCarQR`` written before signing with the real QR URL.

    Raises SifenValidationError when the emitter has no CSC, the XML has no
    ``dCarQR`` or its values cannot form a valid QR.
    """

    qr_url = compute_qr_url_from_signed_xml(signed_xml, emitter=emitter)
    if not _DCARQR_PATTERN.search(signed_xml):
        raise SifenValidationError("documents.qr.dcarqr_element_missing")

    # MT v150 §13.8.4.5: every "&" is written as "&amp;", exactly once.
    element = f"<dCarQR>{escape(qr_url)}</dCarQR>"
    return _DCARQR_PATTERN.sub(lambda _match: element, signed_xml, count=1)


def compute_qr_url_from_signed_xml(signed_xml: str, *, emitter: Emitter) -> str:
    """Return the SIFEN QR URL of a signed XML with the emitter's CSC.

    The CSC only feeds the hash: it never appears in the URL nor in the
    error messages.
    """

    if not emitter.csc or not emitter.csc_id:
        raise SifenValidationError("emitters.csc_required")
    try:
        payload = build_qr_payload_from_signed_xml(
            signed_xml=signed_xml,
            id_csc=emitter.csc_id,
            csc=emitter.csc,
            environment=emitter.tax_environment,
        )
    except ValueError as exc:
        raise SifenValidationError(f"documents.qr.invalid: {exc}") from exc
    return payload["url"]
