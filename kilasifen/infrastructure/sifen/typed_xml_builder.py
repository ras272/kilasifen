"""Build unsigned SIFEN XML from typed document contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from xml.etree import ElementTree as ET

from pysifen.sdk.errors import SifenValidationError
from pysifen.sdk.fiscal import calculate_mod11_dv, generate_cdc

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
ET.register_namespace("", SIFEN_NS)


@dataclass(slots=True)
class TypedXmlBuildResult:
    """Unsigned XML generated from a typed document contract."""

    generated_xml: str
    doc_id: str


def build_typed_document_xml(
    *,
    document: Document,
    emitter: Emitter,
    stamping: Stamping,
) -> TypedXmlBuildResult | None:
    """Build unsigned XML when payload includes a supported typed contract."""

    payload = document.payload_snapshot or {}
    typed_contract = payload.get("typed_contract")
    if not isinstance(typed_contract, dict):
        return None
    contract = str(typed_contract.get("contract") or "").strip()
    typed_payload = typed_contract.get("payload")
    if not isinstance(typed_payload, dict):
        raise SifenValidationError("typed_contract.payload must be an object")

    if contract == "factura_v1":
        return _build_factura_xml(
            typed_payload=typed_payload,
            emitter=emitter,
            stamping=stamping,
        )
    if contract == "nota_credito_v1":
        return _build_nota_credito_xml(
            typed_payload=typed_payload,
            emitter=emitter,
            stamping=stamping,
        )

    return None


def _build_factura_xml(
    *,
    typed_payload: dict,
    emitter: Emitter,
    stamping: Stamping,
) -> TypedXmlBuildResult:
    numero_documento = _required_intlike(typed_payload, "numero")
    fecha_emision = _resolve_emission_date(typed_payload.get("fecha"))
    establecimiento = _normalize_three_digits(typed_payload.get("establecimiento"), "001")
    punto = _normalize_three_digits(typed_payload.get("punto"), "001")
    codigo_seguridad = _normalize_nine_digits(typed_payload.get("codigo_seguridad"), "123456789")
    tipo_contribuyente = _required_intlike(typed_payload, "tipo_contribuyente", default=2)
    cliente = _required_object(typed_payload, "cliente")
    items = _required_items(typed_payload)

    doc_id = _build_doc_id(
        i_tide=1,
        emitter=emitter,
        fecha_emision=fecha_emision,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        tipo_contribuyente=tipo_contribuyente,
        codigo_seguridad=codigo_seguridad,
    )
    totals = _calculate_totals(items)
    root = _build_base_document_root(
        doc_id=doc_id,
        fecha_emision=fecha_emision,
        i_tide=1,
        d_des_tide="Factura electrónica",
        stamping=stamping,
        emitter=emitter,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        codigo_seguridad=codigo_seguridad,
        typed_payload=typed_payload,
        cliente=cliente,
    )
    dtip = _sub(_find_de(root), "gDtipDE")
    gcam_fe = _sub(dtip, "gCamFE")
    indicador_presencia = _required_intlike(typed_payload, "indicador_presencia", default=1)
    _sub(gcam_fe, "iIndPres", str(indicador_presencia))
    _sub(gcam_fe, "dDesIndPres", _presence_description(indicador_presencia))
    _append_condition_node(dtip=dtip, typed_payload=typed_payload, total=totals.total)
    _append_items(dtip=dtip, items=items)
    _append_totals(_find_de(root), totals)
    return TypedXmlBuildResult(
        generated_xml=ET.tostring(root, encoding="unicode", xml_declaration=True),
        doc_id=doc_id,
    )


def _build_nota_credito_xml(
    *,
    typed_payload: dict,
    emitter: Emitter,
    stamping: Stamping,
) -> TypedXmlBuildResult:
    numero_documento = _required_intlike(typed_payload, "numero")
    fecha_emision = _resolve_emission_date(typed_payload.get("fecha"))
    establecimiento = _normalize_three_digits(typed_payload.get("establecimiento"), "001")
    punto = _normalize_three_digits(typed_payload.get("punto"), "001")
    codigo_seguridad = _normalize_nine_digits(typed_payload.get("codigo_seguridad"), "123456789")
    tipo_contribuyente = _required_intlike(typed_payload, "tipo_contribuyente", default=2)
    cliente = _required_object(typed_payload, "cliente")
    items = _required_items(typed_payload)
    asociado = _required_object(typed_payload, "documento_asociado")
    cdc_ref = str(asociado.get("cdc") or "").strip()
    if not cdc_ref:
        raise SifenValidationError("nota_credito.documento_asociado.cdc is required")

    doc_id = _build_doc_id(
        i_tide=5,
        emitter=emitter,
        fecha_emision=fecha_emision,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        tipo_contribuyente=tipo_contribuyente,
        codigo_seguridad=codigo_seguridad,
    )
    totals = _calculate_totals(items)
    root = _build_base_document_root(
        doc_id=doc_id,
        fecha_emision=fecha_emision,
        i_tide=5,
        d_des_tide="Nota de crédito electrónica",
        stamping=stamping,
        emitter=emitter,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        codigo_seguridad=codigo_seguridad,
        typed_payload=typed_payload,
        cliente=cliente,
    )
    dtip = _sub(_find_de(root), "gDtipDE")
    gcam_ncde = _sub(dtip, "gCamNCDE")
    motivo = _required_intlike(typed_payload, "motivo_emision", default=1)
    _sub(gcam_ncde, "iMotEmi", str(motivo))
    _sub(gcam_ncde, "dDesMotEmi", _nota_credito_motive_description(motivo))
    _append_condition_node(dtip=dtip, typed_payload=typed_payload, total=totals.total)
    _append_items(dtip=dtip, items=items)
    _append_totals(_find_de(root), totals)
    asoc = _sub(_find_de(root), "gCamDEAsoc")
    _sub(asoc, "iTipDocAso", "1")
    _sub(asoc, "dDesTipDocAso", "Electrónico")
    _sub(asoc, "dCdCDERef", cdc_ref)
    return TypedXmlBuildResult(
        generated_xml=ET.tostring(root, encoding="unicode", xml_declaration=True),
        doc_id=doc_id,
    )


def _build_base_document_root(
    *,
    doc_id: str,
    fecha_emision: str,
    i_tide: int,
    d_des_tide: str,
    stamping: Stamping,
    emitter: Emitter,
    establecimiento: str,
    punto: str,
    numero_documento: int,
    codigo_seguridad: str,
    typed_payload: dict,
    cliente: dict,
):
    root = ET.Element(_tag("rDE"))
    _sub(root, "dVerFor", "150")
    de = _sub(root, "DE")
    de.set("Id", doc_id)
    _sub(de, "dDVId", str(calculate_mod11_dv(doc_id[:-1])))
    _sub(de, "dFecFirma", fecha_emision)
    _sub(de, "dSisFact", "1")

    gope = _sub(de, "gOpeDE")
    _sub(gope, "iTipEmi", "1")
    _sub(gope, "dDesTipEmi", "Normal")
    _sub(gope, "dCodSeg", codigo_seguridad)

    gtimb = _sub(de, "gTimb")
    _sub(gtimb, "iTiDE", str(i_tide))
    _sub(gtimb, "dDesTiDE", d_des_tide)
    _sub(gtimb, "dNumTim", str(stamping.number))
    _sub(gtimb, "dEst", establecimiento)
    _sub(gtimb, "dPunExp", punto)
    _sub(gtimb, "dNumDoc", f"{numero_documento:07d}")
    _sub(gtimb, "dFeIniT", stamping.start_date.isoformat())
    if stamping.end_date is not None:
        _sub(gtimb, "dFeFinT", stamping.end_date.isoformat())

    gdat = _sub(de, "gDatGralOpe")
    _sub(gdat, "dFeEmiDE", fecha_emision)
    ope = _sub(gdat, "gOpeCom")
    _sub(ope, "iTipTra", "1")
    _sub(ope, "dDesTipTra", "Venta de mercadería")
    _sub(ope, "iTImp", "1")
    _sub(ope, "dDesTImp", "IVA")
    _sub(ope, "cMoneOpe", "PYG")
    _sub(ope, "dDesMoneOpe", "Guarani")

    emis = _sub(gdat, "gEmis")
    _sub(emis, "dRucEm", emitter.ruc)
    _sub(emis, "dDVEmi", emitter.dv)
    _sub(emis, "iTipCont", str(_required_intlike(typed_payload, "tipo_contribuyente", default=2)))
    _sub(emis, "dNomEmi", emitter.legal_name)
    _sub(emis, "dDirEmi", str(typed_payload.get("direccion_emisor") or "ASUNCION"))
    _sub(emis, "dNumCas", str(typed_payload.get("numero_casa_emisor") or "0"))
    _sub(emis, "cDepEmi", str(typed_payload.get("departamento_emisor") or "1"))
    _sub(emis, "dDesDepEmi", str(typed_payload.get("descripcion_departamento_emisor") or "CAPITAL"))
    _sub(emis, "cCiuEmi", str(typed_payload.get("ciudad_emisor") or "1"))
    _sub(
        emis,
        "dDesCiuEmi",
        str(typed_payload.get("descripcion_ciudad_emisor") or "ASUNCION (DISTRITO)"),
    )
    _sub(emis, "dTelEmi", str(typed_payload.get("telefono_emisor") or "021000000"))
    _sub(emis, "dEmailE", str(typed_payload.get("email_emisor") or "facturacion@kila.local"))
    gact = _sub(emis, "gActEco")
    _sub(gact, "cActEco", str(typed_payload.get("codigo_actividad") or "82999"))
    _sub(
        gact,
        "dDesActEco",
        str(
            typed_payload.get("descripcion_actividad")
            or "OTRAS ACTIVIDADES DE SERVICIOS DE APOYO A EMPRESAS N.C.P."
        ),
    )

    rec = _sub(gdat, "gDatRec")
    _sub(rec, "iNatRec", "1")
    _sub(rec, "iTiOpe", "1")
    _sub(rec, "cPaisRec", "PRY")
    _sub(rec, "dDesPaisRe", "Paraguay")
    _sub(rec, "iTiContRec", str(_required_intlike(cliente, "tipo_contribuyente", default=2)))
    ruc_rec, dv_rec = _split_ruc_dv(cliente)
    _sub(rec, "dRucRec", ruc_rec)
    if dv_rec:
        _sub(rec, "dDVRec", dv_rec)
    _sub(rec, "dNomRec", str(cliente.get("razonSocial") or cliente.get("nombre") or "CLIENTE"))
    if cliente.get("direccion"):
        _sub(rec, "dDirRec", str(cliente["direccion"]))
    return root


def _find_de(root: ET.Element) -> ET.Element:
    de = root.find(_tag("DE"))
    if de is None:
        raise SifenValidationError("DE node missing while building typed XML")
    return de


@dataclass(slots=True)
class _Totals:
    sub_exe: Decimal
    sub_5: Decimal
    sub_10: Decimal
    total: Decimal
    iva_5: Decimal
    iva_10: Decimal
    base_5: Decimal
    base_10: Decimal


def _calculate_totals(items: list[dict]) -> _Totals:
    sub_exe = Decimal("0")
    sub_5 = Decimal("0")
    sub_10 = Decimal("0")
    iva_5 = Decimal("0")
    iva_10 = Decimal("0")
    base_5 = Decimal("0")
    base_10 = Decimal("0")
    for item in items:
        qty = _to_decimal(item.get("cantidad"))
        unit_price = _to_decimal(item.get("precioUnitario"))
        amount = (qty * unit_price).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        rate = _required_intlike(item, "iva", default=10)
        if rate == 10:
            current_base = (amount / Decimal("1.10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            current_iva = amount - current_base
            sub_10 += amount
            base_10 += current_base
            iva_10 += current_iva
        elif rate == 5:
            current_base = (amount / Decimal("1.05")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            current_iva = amount - current_base
            sub_5 += amount
            base_5 += current_base
            iva_5 += current_iva
        else:
            sub_exe += amount
    total = sub_exe + sub_5 + sub_10
    return _Totals(
        sub_exe=sub_exe,
        sub_5=sub_5,
        sub_10=sub_10,
        total=total,
        iva_5=iva_5,
        iva_10=iva_10,
        base_5=base_5,
        base_10=base_10,
    )


def _append_condition_node(*, dtip: ET.Element, typed_payload: dict, total: Decimal) -> None:
    gcond = _sub(dtip, "gCamCond")
    condicion = _required_intlike(typed_payload, "condicion_operacion", default=1)
    _sub(gcond, "iCondOpe", str(condicion))
    _sub(gcond, "dDCondOpe", "Contado" if condicion == 1 else "Crédito")
    if condicion == 1:
        pago = _sub(gcond, "gPaConEIni")
        _sub(pago, "iTiPago", "1")
        _sub(pago, "dDesTiPag", "Efectivo")
        _sub(pago, "dMonTiPag", _as_sifen_amount(total))
        _sub(pago, "cMoneTiPag", "PYG")
        _sub(pago, "dDMoneTiPag", "Guarani")


def _append_items(*, dtip: ET.Element, items: list[dict]) -> None:
    for index, item in enumerate(items, start=1):
        current = _sub(dtip, "gCamItem")
        _sub(current, "dCodInt", str(item.get("codigo") or f"ITEM{index:03d}"))
        _sub(current, "dDesProSer", str(item.get("descripcion") or f"Ítem {index}"))
        _sub(current, "cUniMed", str(item.get("codigoUnidad") or "77"))
        _sub(current, "dDesUniMed", str(item.get("unidad") or "UNI"))
        qty = _to_decimal(item.get("cantidad"))
        _sub(current, "dCantProSer", _as_sifen_quantity(qty))

        values = _sub(current, "gValorItem")
        unit_price = _to_decimal(item.get("precioUnitario"))
        item_total = (qty * unit_price).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        _sub(values, "dPUniProSer", _as_sifen_amount(unit_price))
        _sub(values, "dDescItem", "0")
        _sub(values, "dTotOpeItem", _as_sifen_amount(item_total))
        _sub(values, "dTotOpeGs", _as_sifen_amount(item_total))

        rate = _required_intlike(item, "iva", default=10)
        if rate == 10:
            base = (item_total / Decimal("1.10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            liq = item_total - base
            iva_label = "Gravado IVA"
            afec = "1"
        elif rate == 5:
            base = (item_total / Decimal("1.05")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            liq = item_total - base
            iva_label = "Gravado IVA"
            afec = "1"
        else:
            base = Decimal("0")
            liq = Decimal("0")
            iva_label = "Exento"
            afec = "3"

        iva = _sub(current, "gCamIVA")
        _sub(iva, "iAfecIVA", afec)
        _sub(iva, "dDesAfecIVA", iva_label)
        _sub(iva, "dPropIVA", "100")
        _sub(iva, "dTasaIVA", str(rate if rate in {5, 10} else 0))
        _sub(iva, "dBasGravIVA", _as_sifen_amount(base))
        _sub(iva, "dLiqIVAItem", _as_sifen_amount(liq))
        _sub(iva, "dBasExe", "0")


def _append_totals(de: ET.Element, totals: _Totals) -> None:
    gtot = _sub(de, "gTotSub")
    _sub(gtot, "dSubExe", _as_sifen_amount(totals.sub_exe))
    _sub(gtot, "dSubExo", "0")
    _sub(gtot, "dSub5", _as_sifen_amount(totals.sub_5))
    _sub(gtot, "dSub10", _as_sifen_amount(totals.sub_10))
    _sub(gtot, "dTotOpe", _as_sifen_amount(totals.total))
    _sub(gtot, "dTotDesc", "0")
    _sub(gtot, "dTotDescGlotem", "0")
    _sub(gtot, "dTotAntItem", "0")
    _sub(gtot, "dTotAnt", "0")
    _sub(gtot, "dPorcDescTotal", "0.00")
    _sub(gtot, "dDescTotal", "0")
    _sub(gtot, "dAnticipo", "0")
    _sub(gtot, "dRedon", "0")
    _sub(gtot, "dComi", "0")
    _sub(gtot, "dTotGralOpe", _as_sifen_amount(totals.total))
    _sub(gtot, "dIVA5", _as_sifen_amount(totals.iva_5))
    _sub(gtot, "dIVA10", _as_sifen_amount(totals.iva_10))
    _sub(gtot, "dLiqTotIVA5", "0")
    _sub(gtot, "dLiqTotIVA10", "0")
    _sub(gtot, "dIVAComi", "0")
    _sub(gtot, "dTotIVA", _as_sifen_amount(totals.iva_5 + totals.iva_10))
    _sub(gtot, "dBaseGrav5", _as_sifen_amount(totals.base_5))
    _sub(gtot, "dBaseGrav10", _as_sifen_amount(totals.base_10))
    _sub(gtot, "dTBasGraIVA", _as_sifen_amount(totals.base_5 + totals.base_10))
    _sub(gtot, "dTotalGs", _as_sifen_amount(totals.total))


def _build_doc_id(
    *,
    i_tide: int,
    emitter: Emitter,
    fecha_emision: str,
    establecimiento: str,
    punto: str,
    numero_documento: int,
    tipo_contribuyente: int,
    codigo_seguridad: str,
) -> str:
    return generate_cdc(
        i_tide=i_tide,
        d_ruc_em=emitter.ruc,
        d_dv_emi=emitter.dv,
        d_est=establecimiento,
        d_pun_exp=punto,
        d_num_doc=str(numero_documento),
        i_tip_cont=str(tipo_contribuyente),
        d_fe_emi_de=fecha_emision,
        i_tip_emi="1",
        d_cod_seg=codigo_seguridad,
    )


def _required_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise SifenValidationError("items must include at least one item")
    normalized = [item for item in items if isinstance(item, dict)]
    if not normalized:
        raise SifenValidationError("items must include at least one valid item object")
    return normalized


def _required_object(payload: dict, key: str) -> dict:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise SifenValidationError(f"{key} is required")
    return value


def _required_intlike(payload: dict, key: str, default: int | None = None) -> int:
    value = payload.get(key)
    if value is None:
        if default is not None:
            return default
        raise SifenValidationError(f"{key} is required")
    try:
        return int(str(value))
    except ValueError as exc:
        raise SifenValidationError(f"{key} must be an integer") from exc


def _normalize_three_digits(value, fallback: str) -> str:
    if value is None:
        value = fallback
    return f"{int(str(value)):03d}"


def _normalize_nine_digits(value, fallback: str) -> str:
    if value is None:
        value = fallback
    return f"{int(str(value)):09d}"


def _resolve_emission_date(raw: str | None) -> str:
    if raw:
        return str(raw)
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _split_ruc_dv(cliente: dict) -> tuple[str, str | None]:
    ruc = str(cliente.get("ruc") or "").strip()
    if not ruc:
        raise SifenValidationError("cliente.ruc is required")
    if "-" in ruc:
        base, dv = ruc.split("-", 1)
        return base.strip(), dv.strip()
    dv = str(cliente.get("dv") or "").strip() or None
    return ruc, dv


def _presence_description(indicator: int) -> str:
    values = {
        1: "Operación presencial",
        2: "Operación electrónica",
        3: "Operación telefónica",
    }
    return values.get(indicator, "Operación presencial")


def _nota_credito_motive_description(motive: int) -> str:
    values = {
        1: "Devolución y Ajuste de precios",
        2: "Descuento",
        3: "Bonificación",
    }
    return values.get(motive, "Devolución y Ajuste de precios")


def _to_decimal(value) -> Decimal:
    if value is None:
        raise SifenValidationError("numeric value is required")
    return Decimal(str(value))


def _as_sifen_quantity(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f").rstrip("0").rstrip(".") or "0"


def _as_sifen_amount(value: Decimal) -> str:
    return str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tag(name: str) -> str:
    return f"{{{SIFEN_NS}}}{name}"


def _sub(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
    child = ET.SubElement(parent, _tag(name))
    if text is not None:
        child.text = text
    return child
