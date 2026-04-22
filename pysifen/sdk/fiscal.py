"""Fiscal helpers for CDC generation based on SIFEN official rules."""

from __future__ import annotations

from datetime import date, datetime
import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_COMPACT_RE = re.compile(r"^\d{8}$")


def calculate_mod11_dv(value: str, base_max: int = 11) -> int:
    """Calculate modulo-11 verification digit using SET's official routine.

    Non-numeric characters are transformed to their ASCII code (uppercase),
    then the modulo-11 operation is applied from right-to-left with weights
    from 2 up to ``base_max``.
    """

    if base_max < 2:
        raise ValueError("base_max must be >= 2")

    normalized = _to_ascii_digits(value)
    if not normalized:
        raise ValueError("value must not be empty")

    weight = 2
    total = 0
    for char in reversed(normalized):
        if weight > base_max:
            weight = 2
        total += int(char) * weight
        weight += 1

    remainder = total % 11
    if remainder > 1:
        return 11 - remainder
    return 0


def generate_cdc(
    i_tide: int | str,
    d_ruc_em: str,
    d_dv_emi: int | str,
    d_est: int | str,
    d_pun_exp: int | str,
    d_num_doc: int | str,
    i_tip_cont: int | str,
    d_fe_emi_de: date | datetime | str,
    i_tip_emi: int | str,
    d_cod_seg: int | str,
) -> str:
    """Generate CDC (44 chars) from SIFEN official composition."""

    tipo_documento = _numeric_field(i_tide, size=2, name="i_tide", min_value=1)
    ruc_emisor = _normalize_ruc(d_ruc_em)
    dv_emisor = _numeric_field(d_dv_emi, size=1, name="d_dv_emi", min_value=0)
    establecimiento = _numeric_field(d_est, size=3, name="d_est", min_value=0)
    punto_expedicion = _numeric_field(
        d_pun_exp,
        size=3,
        name="d_pun_exp",
        min_value=0,
    )
    numero_documento = _numeric_field(
        d_num_doc,
        size=7,
        name="d_num_doc",
        min_value=0,
    )
    tipo_contribuyente = _numeric_field(
        i_tip_cont,
        size=1,
        name="i_tip_cont",
        min_value=1,
        max_value=2,
    )
    fecha_emision = _normalize_issue_date(d_fe_emi_de)
    tipo_emision = _numeric_field(
        i_tip_emi,
        size=1,
        name="i_tip_emi",
        min_value=1,
        max_value=2,
    )
    codigo_seguridad = _numeric_field(
        d_cod_seg,
        size=9,
        name="d_cod_seg",
        min_value=1,
    )

    if int(codigo_seguridad) == int(numero_documento):
        raise ValueError("d_cod_seg must be different from d_num_doc")

    cdc_without_dv = "".join(
        (
            tipo_documento,
            ruc_emisor,
            dv_emisor,
            establecimiento,
            punto_expedicion,
            numero_documento,
            tipo_contribuyente,
            fecha_emision,
            tipo_emision,
            codigo_seguridad,
        )
    )
    dv_cdc = str(calculate_mod11_dv(cdc_without_dv))
    cdc = f"{cdc_without_dv}{dv_cdc}"

    if len(cdc) != 44:
        raise ValueError(f"generated CDC must have 44 chars, got {len(cdc)}")

    return cdc


def format_cdc_for_kude(cdc: str) -> str:
    """Format CDC in groups of four characters for KuDE representation."""

    cdc = str(cdc).strip()
    if not re.fullmatch(r"\d{44}", cdc):
        raise ValueError("cdc must be exactly 44 numeric characters")
    return " ".join(cdc[i : i + 4] for i in range(0, len(cdc), 4))


def _numeric_field(
    value: int | str,
    *,
    size: int,
    name: str,
    min_value: int | None = None,
    max_value: int | None = None,
) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError(f"{name} must not be empty")
    if not raw.isdigit():
        raise ValueError(f"{name} must contain only digits")

    number = int(raw)
    if min_value is not None and number < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    if max_value is not None and number > max_value:
        raise ValueError(f"{name} must be <= {max_value}")

    formatted = raw.zfill(size)
    if len(formatted) != size:
        raise ValueError(f"{name} must fit in {size} digits")
    return formatted


def _normalize_ruc(value: str) -> str:
    ruc = str(value).strip().upper()
    if not ruc:
        raise ValueError("d_ruc_em must not be empty")
    if "-" in ruc:
        raise ValueError("d_ruc_em must not include DV separator '-'")
    if not re.fullmatch(r"[0-9A-D]{1,8}", ruc):
        raise ValueError("d_ruc_em must match [0-9A-D]{1,8}")
    if any(char in "ABCD" for char in ruc[:-1]):
        raise ValueError("d_ruc_em may include A-D only as the last character")
    return ruc.zfill(8)


def _normalize_issue_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")

    raw = str(value).strip()
    if not raw:
        raise ValueError("d_fe_emi_de must not be empty")
    if _DATE_COMPACT_RE.fullmatch(raw):
        return raw

    # SIFEN field usually comes as YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.
    candidate = raw.split("T", 1)[0]
    if not _DATE_RE.fullmatch(candidate):
        raise ValueError(
            "d_fe_emi_de must be date-like (YYYY-MM-DD, "
            "YYYY-MM-DDTHH:MM:SS or YYYYMMDD)"
        )
    return candidate.replace("-", "")


def _to_ascii_digits(value: str) -> str:
    out = []
    for char in str(value).strip():
        if char.isdigit():
            out.append(char)
        else:
            out.append(str(ord(char.upper())))
    return "".join(out)
