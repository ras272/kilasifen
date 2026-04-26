"""SIFEN QR URL generator (Manual Tecnico v150 section 13.8)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import qrcode

_QR_VERSION = "150"
_URL_BASE_PRODUCCION = "https://ekuatia.set.gov.py/consultas/qr?"
_URL_BASE_TEST = "https://ekuatia.set.gov.py/consultas-test/qr?"


def build_sifen_qr_url(
    *,
    cdc: str,
    fecha_emision: datetime,
    rec_identifier: str,
    total_general: Decimal | int | None,
    total_iva: Decimal | int | None,
    cantidad_items: int,
    digest_value: str,
    csc: str,
    id_csc: str,
    ambiente: str,
) -> str:
    """Build the SIFEN QR URL per Manual Tecnico section 13.8.

    The CSC is consumed for the hash but never appears in the returned URL.
    """

    if not cdc or len(cdc) != 44:
        raise ValueError("cdc must be 44 chars")
    if not csc:
        raise ValueError("csc is required to compute cHashQR")
    if not id_csc:
        raise ValueError("id_csc is required")
    if not digest_value:
        raise ValueError("digest_value is required")

    fecha_str = fecha_emision.strftime("%Y-%m-%dT%H:%M:%S")
    fecha_hex = fecha_str.encode("utf-8").hex()
    digest_hex = digest_value.encode("utf-8").hex()

    receptor = (rec_identifier or "0").strip() or "0"
    total_general_str = _amount_or_zero(total_general)
    total_iva_str = _amount_or_zero(total_iva)

    params = (
        f"nVersion={_QR_VERSION}"
        f"&Id={cdc}"
        f"&dFeEmiDE={fecha_hex}"
        f"&dRucRec={receptor}"
        f"&dTotGralOpe={total_general_str}"
        f"&dTotIVA={total_iva_str}"
        f"&cItems={int(cantidad_items)}"
        f"&DigestValue={digest_hex}"
        f"&IdCSC={id_csc}"
    )

    hash_input = (params + csc).encode("utf-8")
    chash_qr = hashlib.sha256(hash_input).hexdigest()

    base_url = _resolve_base_url(ambiente)
    return f"{base_url}{params}&cHashQR={chash_qr}"


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


def _amount_or_zero(value: Decimal | int | None) -> str:
    if value is None:
        return "0"
    decimal_value = Decimal(str(value))
    if decimal_value == 0:
        return "0"
    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _resolve_base_url(ambiente: str) -> str:
    normalized = (ambiente or "").strip().lower()
    if normalized in {"produccion", "production", "prod"}:
        return _URL_BASE_PRODUCCION
    if normalized in {"test", "testing", "homologacion"}:
        return _URL_BASE_TEST
    raise ValueError(f"unknown ambiente: {ambiente!r}")
