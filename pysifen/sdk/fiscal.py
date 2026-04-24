"""Fiscal helpers for CDC generation based on SIFEN official rules."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_COMPACT_RE = re.compile(r"^\d{8}$")
_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"
)

QR_BASE_URLS = {
    "production": "https://ekuatia.set.gov.py/consultas/qr?",
    "test": "https://ekuatia.set.gov.py/consultas-test/qr?",
}


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


def build_qr_payload(
    *,
    cdc: str,
    d_fe_emi_de: date | datetime | str,
    digest_value: str,
    id_csc: int | str,
    csc: str,
    qr_version: int | str = 150,
    d_ruc_rec: str | None = None,
    d_num_id_rec: str | None = None,
    d_tot_gral_ope: int | float | str | None = None,
    d_tot_iva: int | float | str | None = None,
    c_items: int | str | None = None,
    environment: str = "production",
) -> dict[str, str]:
    """Build QR payload components according to Manual Técnico v150."""

    if d_ruc_rec and d_num_id_rec:
        raise ValueError("use either d_ruc_rec or d_num_id_rec, not both")

    qr_version_value = _numeric_field(
        qr_version,
        size=3,
        name="qr_version",
        min_value=1,
    )
    cdc_value = _validate_cdc(cdc)
    fecha_hex = _to_hex(_normalize_issue_datetime(d_fe_emi_de))
    digest_hex = _to_hex(_normalize_digest_value(digest_value))
    id_csc_value = _numeric_field(
        id_csc,
        size=3,
        name="id_csc",
        min_value=1,
    )
    csc_value = _normalize_csc(csc)

    if d_num_id_rec is not None:
        receptor_key = "dNumIDRec"
        receptor_value = _normalize_receptor(d_num_id_rec)
    else:
        receptor_key = "dRucRec"
        receptor_value = _normalize_receptor(d_ruc_rec)

    total_operacion = _normalize_qr_numeric(d_tot_gral_ope)
    total_iva = _normalize_qr_numeric(d_tot_iva)
    items_value = _normalize_items_count(c_items)

    step1 = (
        f"nVersion={qr_version_value}"
        f"&Id={cdc_value}"
        f"&dFeEmiDE={fecha_hex}"
        f"&{receptor_key}={receptor_value}"
        f"&dTotGralOpe={total_operacion}"
        f"&dTotIVA={total_iva}"
        f"&cItems={items_value}"
        f"&DigestValue={digest_hex}"
        f"&IdCSC={id_csc_value}"
    )
    hash_input = f"{step1}{csc_value}"
    c_hash_qr = sha256(hash_input.encode("utf-8")).hexdigest()

    base_url = _resolve_qr_base_url(environment)
    url = f"{base_url}{step1}&cHashQR={c_hash_qr}"

    if len(url) < 100 or len(url) > 600:
        raise ValueError(
            "generated dCarQR URL length must be between 100 and 600"
        )

    return {
        "step1": step1,
        "hash_input": hash_input,
        "c_hash_qr": c_hash_qr,
        "url": url,
        "dcarqr_xml": url.replace("&", "&amp;"),
    }


def generate_dcarqr(
    *,
    cdc: str,
    d_fe_emi_de: date | datetime | str,
    digest_value: str,
    id_csc: int | str,
    csc: str,
    qr_version: int | str = 150,
    d_ruc_rec: str | None = None,
    d_num_id_rec: str | None = None,
    d_tot_gral_ope: int | float | str | None = None,
    d_tot_iva: int | float | str | None = None,
    c_items: int | str | None = None,
    environment: str = "production",
    xml_escaped: bool = False,
) -> str:
    """Generate dCarQR URL string for XML or external QR rendering."""

    payload = build_qr_payload(
        cdc=cdc,
        d_fe_emi_de=d_fe_emi_de,
        digest_value=digest_value,
        id_csc=id_csc,
        csc=csc,
        qr_version=qr_version,
        d_ruc_rec=d_ruc_rec,
        d_num_id_rec=d_num_id_rec,
        d_tot_gral_ope=d_tot_gral_ope,
        d_tot_iva=d_tot_iva,
        c_items=c_items,
        environment=environment,
    )
    if xml_escaped:
        return payload["dcarqr_xml"]
    return payload["url"]


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


def _normalize_issue_datetime(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return f"{value.strftime('%Y-%m-%d')}T00:00:00"

    raw = str(value).strip()
    if not raw:
        raise ValueError("d_fe_emi_de must not be empty")
    if _DATE_TIME_RE.fullmatch(raw):
        return raw
    if _DATE_RE.fullmatch(raw):
        return f"{raw}T00:00:00"
    raise ValueError(
        "d_fe_emi_de must be datetime-like "
        "(YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)"
    )


def _validate_cdc(value: str) -> str:
    cdc = str(value).strip()
    if not re.fullmatch(r"\d{44}", cdc):
        raise ValueError("cdc must be exactly 44 digits")
    return cdc


def _normalize_digest_value(value: str) -> str:
    digest = str(value).strip()
    if not digest:
        raise ValueError("digest_value must not be empty")
    if len(digest) > 512:
        raise ValueError("digest_value is too long")
    if any(char in "&?" for char in digest):
        raise ValueError("digest_value contains unsupported URL characters")
    return digest


def _normalize_csc(value: str) -> str:
    csc = str(value).strip()
    if not csc:
        raise ValueError("csc must not be empty")
    if not re.fullmatch(r"[0-9A-Za-z]{32}", csc):
        raise ValueError("csc must be 32 alphanumeric characters")
    return csc


def _normalize_receptor(value: str | None) -> str:
    if value is None:
        return "0"
    receptor = str(value).strip()
    if not receptor:
        return "0"
    if len(receptor) > 20:
        raise ValueError("receptor identifier must have max 20 chars")
    if any(char in "&?=" for char in receptor):
        raise ValueError(
            "receptor identifier contains unsupported URL characters"
        )
    return receptor


def _normalize_qr_numeric(value: int | float | str | None) -> str:
    if value is None:
        return "0.00000000"
    if isinstance(value, int | float):
        if value < 0:
            raise ValueError("numeric QR values must be >= 0")
        return f"{Decimal(str(value)):.8f}"

    raw = str(value).strip()
    if not raw:
        return "0.00000000"
    if not re.fullmatch(r"\d+(\.\d+)?", raw):
        raise ValueError("numeric QR values must be digits or decimal string")
    try:
        normalized = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("numeric QR values must be digits or decimal string") from exc
    return f"{normalized:.8f}"


def _normalize_items_count(value: int | str | None) -> str:
    if value is None:
        return "0"
    raw = str(value).strip()
    if not raw.isdigit():
        raise ValueError("c_items must contain only digits")
    if int(raw) < 0:
        raise ValueError("c_items must be >= 0")
    return raw


def _resolve_qr_base_url(environment: str) -> str:
    key = str(environment).strip().lower()
    if key not in QR_BASE_URLS:
        raise ValueError(
            "environment must be either 'production' or 'test'"
        )
    return QR_BASE_URLS[key]


def _to_hex(value: str) -> str:
    return value.encode("utf-8").hex()


def _to_ascii_digits(value: str) -> str:
    out = []
    for char in str(value).strip():
        if char.isdigit():
            out.append(char)
        else:
            out.append(str(ord(char.upper())))
    return "".join(out)
