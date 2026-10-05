"""Utilidades fiscales del SIFEN: digito verificador, CDC y codigo QR.

El QR (``gCamFuFD/dCarQR``) tiene una sola implementacion, basada en los
valores literales del DE firmado (MT v150 §13.8; NT 10 §3 y §4; NT 23 §1.1):
la validacion 2500 compara la cadena del QR con los campos del XML, asi que
ningun valor se recalcula ni se reformatea.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from xml.etree import ElementTree as ET

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_COMPACT_RE = re.compile(r"^\d{8}$")

QR_BASE_URLS = {
    "production": "https://ekuatia.set.gov.py/consultas/qr?",
    "test": "https://ekuatia.set.gov.py/consultas-test/qr?",
}
SIFEN_XML_NS = "http://ekuatia.set.gov.py/sifen/xsd"
DS_XML_NS = "http://www.w3.org/2000/09/xmldsig#"

#: Longitud del valor de ``dCarQR`` sin escapar (XSD ``tgCamFuFD``; MT v150
#: J002, p. 110).
QR_URL_MIN_LENGTH = 100
QR_URL_MAX_LENGTH = 600

_QR_NS = {"s": SIFEN_XML_NS, "ds": DS_XML_NS}
# D002, XSD fecHhmmss.
_QR_ISSUE_DATETIME_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
)
# F014/F017, XSD tMontoBase (xs:decimal no negativo, sin signo ni exponente).
_QR_AMOUNT_RE = re.compile(r"[0-9]+(\.[0-9]+)?")
# D206, XSD tRuc (RUC sin DV, de 3 a 8 caracteres).
_QR_RUC_REC_RE = re.compile(r"[1-9][0-9]*[0-9A-D]?")
# D210, XSD tdNumDocId.
_QR_NUM_ID_REC_RE = re.compile(r"[0-9A-Za-z\-]{1,20}")
# XS17: texto base64 del DigestValue.
_QR_DIGEST_VALUE_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
# MT v150 §13.8.1: el CSC son 32 caracteres alfanumericos.
_CSC_RE = re.compile(r"[0-9A-Za-z]{32}")


def calculate_mod11_dv(value: str, base_max: int = 11) -> int:
    """Calcula el digito verificador modulo 11 con la rutina oficial de la SET.

    Cada caracter no numerico se reemplaza por su codigo ASCII (en
    mayusculas) y el modulo 11 se aplica de derecha a izquierda con pesos de
    2 hasta ``base_max``.
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
    """Genera el CDC de 44 caracteres con la composicion oficial (MT v150 §10)."""

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
    """Agrupa el CDC de a cuatro caracteres, como se imprime en el KuDE."""

    cdc = str(cdc).strip()
    if not re.fullmatch(r"[0-9]{44}", cdc):
        raise ValueError("cdc must be exactly 44 numeric characters")
    return " ".join(cdc[i : i + 4] for i in range(0, len(cdc), 4))


@dataclass(frozen=True)
class _ValoresQR:
    """Valores del Paso 1 (MT v150 §13.8.4.1), ya validados y sin el CSC."""

    version: str
    cdc: str
    fecha_emision: str
    parametro_receptor: str
    receptor: str
    total_operacion: str
    total_iva: str
    items: str
    digest_value: str


def build_qr_payload(
    *,
    cdc: str,
    d_fe_emi_de: datetime | str,
    digest_value: str,
    id_csc: int | str,
    csc: str,
    qr_version: int | str = 150,
    d_ruc_rec: str | None = None,
    d_num_id_rec: str | None = None,
    d_tot_gral_ope: int | Decimal | str | None = None,
    d_tot_iva: int | Decimal | str | None = None,
    c_items: int | str | None = None,
    environment: str = "production",
) -> dict[str, str]:
    """Arma el QR de un DE con el texto de sus campos (MT v150 §13.8).

    Cada valor tiene que ser el texto del campo en el XML firmado, porque el
    SIFEN compara el QR con el XML (validacion 2500):

    - ``d_fe_emi_de``: texto de D002 (``AAAA-MM-DDThh:mm:ss``) o un
      ``datetime``; una fecha sin hora se rechaza.
    - ``d_ruc_rec``: D206 (RUC sin DV) si ``iNatRec`` es 1; ``d_num_id_rec``:
      D210 si ``iNatRec`` es 2 (``0`` en el innominado, NT 23 §1.1, y ``0``
      cuando el DE no trae D210, nota (*) de la tabla de §13.8.2). Hay que
      pasar exactamente uno: sin ninguno se lanza ``ValueError`` en lugar de
      suponer el receptor, porque un QR que no coincide con el XML lo rechaza
      la validacion 2500.
    - ``d_tot_gral_ope`` y ``d_tot_iva``: texto de F014 y F017, o ``0`` si el
      DE no los informa (MT v150 §13.8.4.1; NT 10 §4, obs. 1). Un ``float``
      se rechaza porque no conserva el literal del XML.
    - ``c_items``: cantidad de ocurrencias de E701.

    Devuelve ``step1`` (el Paso 1, sin el CSC), ``c_hash_qr``, ``url`` (el
    valor de ``dCarQR``) y ``dcarqr_xml``, la misma URL con ``&amp;`` que solo
    sirve para insertarla en texto XML crudo: asignada a un nodo quedaria
    escapada dos veces. Ningun valor devuelto contiene el CSC (MT v150
    §13.8.4.2).
    """

    parametro_receptor, receptor = _qr_receptor_from_values(
        d_ruc_rec=d_ruc_rec,
        d_num_id_rec=d_num_id_rec,
    )
    valores = _ValoresQR(
        version=_qr_version(qr_version),
        cdc=_validate_cdc(cdc),
        fecha_emision=_qr_issue_datetime(d_fe_emi_de),
        parametro_receptor=parametro_receptor,
        receptor=receptor,
        total_operacion=_qr_amount(d_tot_gral_ope, name="d_tot_gral_ope"),
        total_iva=_qr_amount(d_tot_iva, name="d_tot_iva"),
        items=_qr_items_count(c_items),
        digest_value=_qr_digest_value(digest_value),
    )
    return _build_qr(valores, id_csc=id_csc, csc=csc, environment=environment)


def generate_dcarqr(
    *,
    cdc: str,
    d_fe_emi_de: datetime | str,
    digest_value: str,
    id_csc: int | str,
    csc: str,
    qr_version: int | str = 150,
    d_ruc_rec: str | None = None,
    d_num_id_rec: str | None = None,
    d_tot_gral_ope: int | Decimal | str | None = None,
    d_tot_iva: int | Decimal | str | None = None,
    c_items: int | str | None = None,
    environment: str = "production",
    xml_escaped: bool = False,
) -> str:
    """Devuelve la URL de ``dCarQR`` de :func:`build_qr_payload`.

    Con ``xml_escaped=True`` la devuelve con ``&amp;``, solo para insertarla
    en texto XML crudo.
    """

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


def build_qr_payload_from_signed_xml(
    *,
    signed_xml: str | bytes,
    id_csc: int | str,
    csc: str,
    qr_version: int | str | None = None,
    environment: str = "production",
) -> dict[str, str]:
    """Arma el QR con los valores literales de un ``rDE`` firmado.

    Los valores salen del XML tal cual (MT v150 §13.8.2):

    - ``nVersion``: texto de ``dVerFor`` (AA002). ``qr_version``, si se pasa,
      tiene que coincidir con el.
    - ``Id``: atributo ``Id`` del ``DE`` (A002).
    - ``dFeEmiDE``: texto de D002, en hexadecimal.
    - receptor: ``dRucRec`` con D206 si ``iNatRec`` es 1; ``dNumIDRec`` con
      D210, o ``0`` si no esta, si ``iNatRec`` es 2 (NT 23 §1.1).
    - ``dTotGralOpe`` y ``dTotIVA``: texto de F014 y F017, o ``0`` cuando el
      DE no los informa (nota de remision, autofactura, DE sin IVA; MT v150
      p. 102 y §13.8.4.1; NT 10 §4, obs. 1).
    - ``cItems``: cantidad de ``gCamItem``.
    - ``DigestValue``: texto de ``Signature/SignedInfo/Reference/DigestValue``
      (XS17), en hexadecimal; por eso el QR se calcula despues de firmar.

    Devuelve lo mismo que :func:`build_qr_payload`.
    """

    root = _parse_signed_xml_root(signed_xml)
    de = root.find("s:DE", _QR_NS)
    if de is None:
        raise ValueError("signed_xml must include rDE/DE")
    cdc = de.get("Id")
    if not cdc:
        raise ValueError("signed_xml DE must include Id (CDC)")

    parametro_receptor, receptor = _qr_receptor_from_xml(de)
    valores = _ValoresQR(
        version=_qr_version_from_xml(root, requested=qr_version),
        cdc=_validate_cdc(cdc),
        fecha_emision=_qr_issue_datetime(
            _required_xml_text(de, "s:gDatGralOpe/s:dFeEmiDE", field_name="dFeEmiDE")
        ),
        parametro_receptor=parametro_receptor,
        receptor=receptor,
        total_operacion=_qr_amount(
            _optional_xml_text(de, "s:gTotSub/s:dTotGralOpe"), name="dTotGralOpe"
        ),
        total_iva=_qr_amount(
            _optional_xml_text(de, "s:gTotSub/s:dTotIVA"), name="dTotIVA"
        ),
        items=str(len(de.findall("s:gDtipDE/s:gCamItem", _QR_NS))),
        digest_value=_qr_digest_value(
            _required_xml_text(
                root,
                "ds:Signature/ds:SignedInfo/ds:Reference/ds:DigestValue",
                field_name="ds:DigestValue",
            )
        ),
    )
    return _build_qr(valores, id_csc=id_csc, csc=csc, environment=environment)


def generate_dcarqr_from_signed_xml(
    *,
    signed_xml: str | bytes,
    id_csc: int | str,
    csc: str,
    qr_version: int | str | None = None,
    environment: str = "production",
    xml_escaped: bool = False,
) -> str:
    """Devuelve la URL de ``dCarQR`` de :func:`build_qr_payload_from_signed_xml`."""

    payload = build_qr_payload_from_signed_xml(
        signed_xml=signed_xml,
        id_csc=id_csc,
        csc=csc,
        qr_version=qr_version,
        environment=environment,
    )
    if xml_escaped:
        return payload["dcarqr_xml"]
    return payload["url"]


def _build_qr(
    valores: _ValoresQR,
    *,
    id_csc: int | str,
    csc: str,
    environment: str,
) -> dict[str, str]:
    base_url = _resolve_qr_base_url(environment)
    # IdCSC con 4 digitos, como en todos los ejemplos oficiales (MT v150
    # §13.8.3-§13.8.4; Guia de Pruebas 2026: 0001 y 0002).
    id_csc_value = _numeric_field(id_csc, size=4, name="id_csc", min_value=1)
    csc_value = _normalize_csc(csc)

    # Orden de la tabla de MT v150 §13.8.2; fecha y DigestValue en hex
    # (§13.8.3).
    step1 = "&".join(
        f"{nombre}={valor}"
        for nombre, valor in (
            ("nVersion", valores.version),
            ("Id", valores.cdc),
            ("dFeEmiDE", _to_hex(valores.fecha_emision)),
            (valores.parametro_receptor, valores.receptor),
            ("dTotGralOpe", valores.total_operacion),
            ("dTotIVA", valores.total_iva),
            ("cItems", valores.items),
            ("DigestValue", _to_hex(valores.digest_value)),
            ("IdCSC", id_csc_value),
        )
    )
    # SHA-256 del Paso 1 seguido del CSC, sin separador, en hex minusculas
    # (MT v150 §13.8.4.2-§13.8.4.3). El CSC nunca va en la URL.
    c_hash_qr = sha256(f"{step1}{csc_value}".encode("ascii")).hexdigest()
    url = f"{base_url}{step1}&cHashQR={c_hash_qr}"

    if not QR_URL_MIN_LENGTH <= len(url) <= QR_URL_MAX_LENGTH:
        raise ValueError(
            "generated dCarQR URL length must be between 100 and 600"
        )

    return {
        "step1": step1,
        "c_hash_qr": c_hash_qr,
        "url": url,
        "dcarqr_xml": url.replace("&", "&amp;"),
    }


def _qr_receptor_from_values(
    *,
    d_ruc_rec: str | None,
    d_num_id_rec: str | None,
) -> tuple[str, str]:
    ruc = _blank_to_none(d_ruc_rec)
    numero = _blank_to_none(d_num_id_rec)
    if ruc is not None and numero is not None:
        raise ValueError("use either d_ruc_rec or d_num_id_rec, not both")
    if ruc is not None:
        return "dRucRec", _qr_ruc_rec(ruc)
    if numero is None:
        # El receptor no se supone (validacion 2500): D206 si iNatRec es 1,
        # D210 (o "0") si es 2.
        raise ValueError(
            "pass d_ruc_rec (D206, iNatRec 1) or d_num_id_rec "
            "(D210, or 0 without D210, iNatRec 2)"
        )
    return "dNumIDRec", _qr_num_id_rec(numero)


def _qr_receptor_from_xml(de: ET.Element) -> tuple[str, str]:
    receptor = "s:gDatGralOpe/s:gDatRec/"
    naturaleza = _required_xml_text(de, f"{receptor}s:iNatRec", field_name="iNatRec")
    if naturaleza == "1":
        ruc = _required_xml_text(de, f"{receptor}s:dRucRec", field_name="dRucRec")
        return "dRucRec", _qr_ruc_rec(ruc)
    if naturaleza == "2":
        numero = _optional_xml_text(de, f"{receptor}s:dNumIDRec")
        return "dNumIDRec", _qr_num_id_rec(numero or "0")
    raise ValueError("signed_xml iNatRec must be 1 or 2")


def _qr_version_from_xml(root: ET.Element, *, requested: int | str | None) -> str:
    version = _qr_version(
        _required_xml_text(root, "s:dVerFor", field_name="dVerFor")
    )
    if requested is not None and _qr_version(requested) != version:
        raise ValueError("qr_version must match the dVerFor of signed_xml")
    return version


def _qr_version(value: int | str) -> str:
    return _numeric_field(value, size=3, name="qr_version", min_value=1)


def _qr_issue_datetime(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    # Texto de D002 (tambien el XmlDateTime de xsdata, que se imprime igual).
    text = str(value).strip()
    if _QR_ISSUE_DATETIME_RE.fullmatch(text):
        return text
    raise ValueError(
        "d_fe_emi_de must be the D002 text (YYYY-MM-DDTHH:MM:SS) or a datetime"
    )


def _qr_ruc_rec(value: str) -> str:
    ruc = value.strip()
    if not (3 <= len(ruc) <= 8 and _QR_RUC_REC_RE.fullmatch(ruc)):
        raise ValueError("d_ruc_rec must be the D206 text (RUC without DV)")
    return ruc


def _qr_num_id_rec(value: str) -> str:
    numero = value.strip()
    if not _QR_NUM_ID_REC_RE.fullmatch(numero):
        raise ValueError("d_num_id_rec must be the D210 text")
    return numero


def _qr_amount(value: int | Decimal | str | None, *, name: str) -> str:
    if value is None:
        return "0"
    if isinstance(value, (bool, float)):
        raise ValueError(
            f"{name} must be the XML text, an int or a Decimal; "
            "a float does not keep the literal"
        )
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, Decimal):
        text = format(value, "f") if value.is_finite() else ""
    else:
        text = str(value).strip()
        if not text:
            return "0"
    if not _QR_AMOUNT_RE.fullmatch(text):
        raise ValueError(f"{name} must be a non-negative decimal literal")
    return text


def _qr_items_count(value: int | str | None) -> str:
    if value is None:
        return "0"
    if isinstance(value, bool):
        raise ValueError("c_items must contain only digits")
    raw = str(value).strip()
    if not (raw.isascii() and raw.isdigit()):
        raise ValueError("c_items must contain only digits")
    return str(int(raw))


def _qr_digest_value(value: str) -> str:
    digest = str(value).strip()
    if not digest:
        raise ValueError("digest_value must not be empty")
    if len(digest) > 512 or not _QR_DIGEST_VALUE_RE.fullmatch(digest):
        raise ValueError("digest_value must be the base64 text of DigestValue")
    return digest


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    if not (raw.isascii() and raw.isdigit()):
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


def _parse_signed_xml_root(signed_xml: str | bytes) -> ET.Element:
    if isinstance(signed_xml, bytes):
        raw = signed_xml
    else:
        raw = str(signed_xml).encode("utf-8")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("signed_xml must be a valid XML document") from exc


def _optional_xml_text(element: ET.Element, xpath: str) -> str | None:
    node = element.find(xpath, _QR_NS)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    if not value:
        return None
    return value


def _required_xml_text(element: ET.Element, xpath: str, *, field_name: str) -> str:
    value = _optional_xml_text(element, xpath)
    if value is None:
        raise ValueError(f"signed_xml must include {field_name}")
    return value


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

    # D002 llega como AAAA-MM-DD o AAAA-MM-DDThh:mm:ss.
    candidate = raw.split("T", 1)[0]
    if not _DATE_RE.fullmatch(candidate):
        raise ValueError(
            "d_fe_emi_de must be date-like (YYYY-MM-DD, "
            "YYYY-MM-DDTHH:MM:SS or YYYYMMDD)"
        )
    return candidate.replace("-", "")


def _validate_cdc(value: str) -> str:
    cdc = str(value).strip()
    if not re.fullmatch(r"[0-9]{44}", cdc):
        raise ValueError("cdc must be exactly 44 digits")
    return cdc


def _normalize_csc(value: str) -> str:
    csc = str(value).strip()
    if not csc:
        raise ValueError("csc must not be empty")
    if not _CSC_RE.fullmatch(csc):
        raise ValueError("csc must be 32 alphanumeric characters")
    return csc


def _resolve_qr_base_url(environment: str) -> str:
    # URL sin www de la NT 10 §3.1, que reemplaza la de MT v150 p. 208.
    key = str(environment).strip().lower()
    if key not in QR_BASE_URLS:
        raise ValueError(
            "environment must be either 'production' or 'test'"
        )
    return QR_BASE_URLS[key]


def _to_hex(value: str) -> str:
    return value.encode("ascii").hex()


def _to_ascii_digits(value: str) -> str:
    out = []
    for char in str(value).strip():
        if char.isdigit():
            out.append(char)
        else:
            out.append(str(ord(char.upper())))
    return "".join(out)
