"""Render the SIFEN QR of a KuDE.

The QR URL itself is ``gCamFuFD/dCarQR`` of the signed XML, computed by
:func:`kilasifen.engine.sdk.fiscal.build_qr_payload_from_signed_xml`; this
module only draws it.
"""

from __future__ import annotations

from io import BytesIO

import qrcode


def render_qr_image(url: str, *, box_size: int = 5) -> bytes:
    """Render the QR URL as a PNG byte string."""

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
