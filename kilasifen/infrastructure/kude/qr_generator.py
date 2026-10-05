"""Render the SIFEN QR of a KuDE.

The QR URL itself is ``gCamFuFD/dCarQR`` of the signed XML, computed by
:func:`kilasifen.engine.sdk.fiscal.build_qr_payload_from_signed_xml`; this
module only draws it.
"""

from __future__ import annotations

import math
from io import BytesIO

import qrcode

#: ISO/IEC 18004, the standard MT v150 §13.8.1 follows, asks for a quiet
#: zone of at least four modules around the symbol.
MIN_QUIET_ZONE_MODULES = 4


def quiet_zone_modules(modules_count: int) -> int:
    """Return the quiet zone, in modules, for a symbol of ``modules_count``.

    At least four modules (ISO/IEC 18004) and, since the KuDE prints the QR
    wider than 25 mm, a safe margin of at least 10% of the image width (MT
    v150 §13.8.1 p. 205): ``2b / (n + 2b) >= 0.10`` holds for ``b >= n / 18``.
    """

    return max(MIN_QUIET_ZONE_MODULES, math.ceil(modules_count / 18))


def render_qr_image(url: str, *, box_size: int = 5) -> bytes:
    """Render the QR URL as a PNG byte string, quiet zone included."""

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=MIN_QUIET_ZONE_MODULES,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr.border = quiet_zone_modules(qr.modules_count)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
