"""Extract structured KuDE data from a signed SIFEN DE XML.

This module is the single source of truth for both the PDF renderer and
the JSON endpoint. Walks the signed XML and produces a normalized dict
ready to render. The CSC is never read, logged or returned.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.engine.sdk.errors import SifenValidationError

_NS = "http://ekuatia.set.gov.py/sifen/xsd"

_DOC_TYPE_LABELS = {
    "1": ("factura_electronica", "KuDE de Factura Electrónica", "Factura Electrónica"),
    "5": (
        "nota_credito_electronica",
        "KuDE de Nota de Crédito Electrónica",
        "Nota de Crédito Electrónica",
    ),
    "6": (
        "nota_debito_electronica",
        "KuDE de Nota de Débito Electrónica",
        "Nota de Débito Electrónica",
    ),
}

_CONDITION_LABELS = {"1": ("contado", "Contado"), "2": ("credito", "Crédito")}

_NATURE_LABELS = {"1": "contribuyente", "2": "no_contribuyente"}

_OPERATION_TYPE_LABELS = {"1": "B2B", "2": "B2C", "3": "B2G", "4": "B2F"}

_AFFECTATION_LABELS = {
    "1": "gravado_iva",
    "2": "exonerado",
    "3": "exento",
    "4": "gravado_parcial",
}

_TEST_AMBIENTE_WARNING = (
    "DE generado en ambiente de prueba - sin valor comercial ni fiscal"
)


def extract_kude_data(*, document: Document, emitter: Emitter) -> dict:
    """Build the normalized KuDE dict for one signed document."""

    signed_xml = _resolve_signed_xml(document)
    root = ET.fromstring(signed_xml.encode("utf-8"))
    de = _required(root, "DE")
    g_timb = _required(de, "gTimb")
    g_gral = _required(de, "gDatGralOpe")
    g_emis = _required(g_gral, "gEmis")
    g_rec = _required(g_gral, "gDatRec")
    g_ope = _required(g_gral, "gOpeCom")
    g_dtip = _required(de, "gDtipDE")
    g_tot = _required(de, "gTotSub")
    g_fuera = root.find(_t("gCamFuFD"))

    cdc_raw = de.attrib.get("Id") or ""
    if len(cdc_raw) != 44:
        raise SifenValidationError("documents.kude.cdc_invalid")

    i_tide = _text(g_timb, "iTiDE") or "1"
    tipo_key, tipo_label, doc_type_short = _DOC_TYPE_LABELS.get(
        i_tide, ("desconocido", "KuDE", "Documento Electrónico")
    )

    ambiente = (
        "test" if (emitter.tax_environment or "").lower() == "test" else "produccion"
    )
    portal_root = (
        "https://ekuatia.set.gov.py/consultas-test/"
        if ambiente == "test"
        else "https://ekuatia.set.gov.py/consultas/"
    )

    emisor = _build_emisor(g_emis)
    timbrado = _build_timbrado(g_timb, doc_type_short)
    datos_generales = _build_datos_generales(g_gral, g_ope, g_dtip)
    receptor = _build_receptor(g_rec)
    documento_asociado = _build_documento_asociado(de)
    adjustment_note = _build_adjustment_note(g_dtip) if i_tide in {"5", "6"} else None
    items = _build_items(g_dtip)
    totales = _build_totales(g_tot, moneda=datos_generales["moneda"])
    qr_url = _text(g_fuera, "dCarQR") if g_fuera is not None else None

    return {
        "kude": {
            "tipo": tipo_key,
            "tipo_label": tipo_label,
            "ambiente": ambiente,
            "ambiente_warning": _TEST_AMBIENTE_WARNING if ambiente == "test" else None,
            "cdc": {
                "raw": cdc_raw,
                "groups": [cdc_raw[i : i + 4] for i in range(0, 44, 4)],
            },
            "emisor": emisor,
            "timbrado": timbrado,
            "datos_generales": datos_generales,
            "receptor": receptor,
            "documento_asociado": documento_asociado,
            "nota_credito": adjustment_note if i_tide == "5" else None,
            "nota_debito": adjustment_note if i_tide == "6" else None,
            "items": items,
            "totales": totales,
            "qr": {"url": qr_url, "ambiente": ambiente},
            "consulta_publica": {"portal_url": portal_root},
            "informacion_adicional": None,
        }
    }


def _resolve_signed_xml(document: Document) -> str:
    if document.signed_xml:
        return document.signed_xml
    payload = document.payload_snapshot or {}
    if isinstance(payload.get("signed_xml"), str):
        return payload["signed_xml"]
    raise SifenValidationError("documents.kude.signed_xml_missing")


def _build_emisor(g_emis: ET.Element) -> dict:
    ruc = _text(g_emis, "dRucEm") or ""
    dv = _text(g_emis, "dDVEmi") or ""
    activity = g_emis.find(_t("gActEco"))
    return {
        "ruc": ruc,
        "dv": dv,
        "ruc_dv": f"{ruc}-{dv}" if ruc and dv else ruc,
        "razon_social": _text(g_emis, "dNomEmi") or "",
        "nombre_fantasia": _text(g_emis, "dNomFanEmi"),
        "actividad_economica": {
            "codigo": _text(activity, "cActEco") if activity is not None else None,
            "descripcion": _text(activity, "dDesActEco")
            if activity is not None
            else None,
        },
        "direccion": _text(g_emis, "dDirEmi") or "",
        "ciudad": _text(g_emis, "dDesCiuEmi") or "",
        "departamento": _text(g_emis, "dDesDepEmi"),
        "telefono": _text(g_emis, "dTelEmi"),
        "email": _text(g_emis, "dEmailE"),
    }


def _build_timbrado(g_timb: ET.Element, doc_type_short: str) -> dict:
    est = _text(g_timb, "dEst") or ""
    punto = _text(g_timb, "dPunExp") or ""
    numero = _text(g_timb, "dNumDoc") or ""
    return {
        "numero": _text(g_timb, "dNumTim") or "",
        "fecha_inicio_vigencia": _text(g_timb, "dFeIniT") or "",
        "fecha_fin_vigencia": _text(g_timb, "dFeFinT"),
        "tipo_documento_label": doc_type_short,
        "numero_documento": f"{est}-{punto}-{numero}",
    }


def _build_datos_generales(
    g_gral: ET.Element, g_ope: ET.Element, g_dtip: ET.Element
) -> dict:
    moneda = _text(g_ope, "cMoneOpe") or "PYG"
    moneda_label = _text(g_ope, "dDesMoneOpe") or "Guarani"
    g_cond = g_dtip.find(_t("gCamCond"))
    cond_code = _text(g_cond, "iCondOpe") if g_cond is not None else None
    cond_key, cond_label = _CONDITION_LABELS.get(cond_code, (None, None))

    cuotas = None
    if g_cond is not None and cond_code == "2":
        g_credito = g_cond.find(_t("gPagCred"))
        if g_credito is not None:
            cuotas_text = _text(g_credito, "dCantCuoCre")
            if cuotas_text:
                try:
                    cuotas = int(cuotas_text)
                except ValueError:
                    cuotas = None

    return {
        "fecha_emision": _text(g_gral, "dFeEmiDE") or "",
        "condicion_operacion": cond_key,
        "condicion_operacion_label": cond_label,
        "cantidad_cuotas": cuotas,
        "moneda": moneda,
        "moneda_label": moneda_label,
        "tipo_cambio": _text(g_ope, "dTiCam"),
        "tipo_transaccion_label": _text(g_ope, "dDesTipTra") or "",
    }


def _build_receptor(g_rec: ET.Element) -> dict:
    nature_code = _text(g_rec, "iNatRec") or "2"
    op_code = _text(g_rec, "iTiOpe") or ""
    ruc = _text(g_rec, "dRucRec")
    dv = _text(g_rec, "dDVRec")
    ruc_dv = f"{ruc}-{dv}" if ruc and dv else ruc
    return {
        "naturaleza": _NATURE_LABELS.get(nature_code, "no_contribuyente"),
        "tipo_operacion": _OPERATION_TYPE_LABELS.get(op_code, op_code),
        "ruc": ruc,
        "dv": dv,
        "ruc_dv": ruc_dv,
        "tipo_documento_identidad": _text(g_rec, "dDTipIDRec"),
        "numero_documento_identidad": _text(g_rec, "dNumIDRec"),
        "razon_social": _text(g_rec, "dNomRec") or "",
        "nombre_fantasia": _text(g_rec, "dNomFanRec"),
        "direccion": _text(g_rec, "dDirRec"),
        "telefono": _text(g_rec, "dTelRec"),
        "email": _text(g_rec, "dEmailRec"),
    }


def _build_documento_asociado(de: ET.Element) -> dict | None:
    asoc = de.find(_t("gCamDEAsoc"))
    if asoc is None:
        return None
    tipo_code = _text(asoc, "iTipDocAso")
    if tipo_code == "1":
        return {
            "tipo": "electronico",
            "cdc": _text(asoc, "dCdCDERef"),
            "timbrado": None,
            "establecimiento": None,
            "punto": None,
            "numero": None,
            "fecha_emision": None,
        }
    if tipo_code == "2":
        return {
            "tipo": "impreso",
            "cdc": None,
            "timbrado": _text(asoc, "dNTimDI"),
            "establecimiento": _text(asoc, "dEstDocAso"),
            "punto": _text(asoc, "dPExpDocAso"),
            "numero": _text(asoc, "dNumDocAso"),
            "fecha_emision": _text(asoc, "dFecEmiDI"),
        }
    return None


def _build_adjustment_note(g_dtip: ET.Element) -> dict | None:
    g_nc = g_dtip.find(_t("gCamNCDE"))
    if g_nc is None:
        return None
    code = _text(g_nc, "iMotEmi")
    try:
        code_int = int(code) if code else 0
    except ValueError:
        code_int = 0
    return {
        "motivo_codigo": code_int,
        "motivo_label": _text(g_nc, "dDesMotEmi") or "",
    }


def _build_items(g_dtip: ET.Element) -> list[dict]:
    out: list[dict] = []
    for item in g_dtip.findall(_t("gCamItem")):
        valor = item.find(_t("gValorItem"))
        iva = item.find(_t("gCamIVA"))
        descuento = "0"
        anticipo = "0"
        valor_total = ""
        if valor is not None:
            restas = valor.find(_t("gValorRestaItem"))
            if restas is not None:
                valor_total = _text(restas, "dTotOpeItem") or ""
                descuento = _text(restas, "dDescItem") or "0"
                anticipo = _text(restas, "dAntPreUniIt") or "0"

        afect_code = _text(iva, "iAfecIVA") if iva is not None else "1"
        tasa_text = _text(iva, "dTasaIVA") if iva is not None else "0"
        try:
            tasa = int(float(tasa_text)) if tasa_text else 0
        except ValueError:
            tasa = 0
        afect_key = _AFFECTATION_LABELS.get(afect_code, "gravado_iva")
        valor_exento = "0"
        valor_5 = "0"
        valor_10 = "0"
        if afect_key in {"exento", "exonerado"}:
            valor_exento = valor_total or "0"
        elif tasa == 5:
            valor_5 = valor_total or "0"
        else:
            valor_10 = valor_total or "0"

        unidad_med = _text(item, "cUniMed") or ""
        unidad_label = _text(item, "dDesUniMed") or ""
        out.append(
            {
                "codigo": _text(item, "dCodInt") or "",
                "descripcion": _text(item, "dDesProSer") or "",
                "unidad_medida": {"codigo": unidad_med, "label": unidad_label},
                "cantidad": _text(item, "dCantProSer") or "",
                "precio_unitario": _text(valor, "dPUniProSer")
                if valor is not None
                else "",
                "descuento": descuento,
                "anticipo": anticipo,
                "valor_total": valor_total,
                "afectacion_iva": afect_key,
                "tasa_iva": tasa,
                "valor_exento": valor_exento,
                "valor_5": valor_5,
                "valor_10": valor_10,
            }
        )
    return out


def _build_totales(g_tot: ET.Element, *, moneda: str) -> dict:
    total_general = _text(g_tot, "dTotGralOpe") or "0"
    # MT v150 §13.4.3 "Total en Guaraníes": F014 when the operation is in
    # PYG; otherwise F023 dTotalGs (NT 08 §1.2), never recomputed here, so a
    # foreign-currency XML without F023 has none (None).
    if moneda.strip().upper() == "PYG":
        total_guaranies = total_general
    else:
        total_guaranies = _text(g_tot, "dTotalGs")
    return {
        "subtotal_exentas": _text(g_tot, "dSubExe") or "0",
        # F003 and F025 are 0-1 (MT v150 pp. 102-104): None when absent.
        "subtotal_exonerado": _text(g_tot, "dSubExo"),
        "subtotal_5": _text(g_tot, "dSub5") or "0",
        "subtotal_10": _text(g_tot, "dSub10") or "0",
        "total_operacion": _text(g_tot, "dTotOpe") or "0",
        "total_descuentos": _text(g_tot, "dTotDesc") or "0",
        "total_anticipos": _text(g_tot, "dTotAnt") or "0",
        "redondeo": _text(g_tot, "dRedon") or "0",
        "comision": _text(g_tot, "dComi"),
        "total_general_operacion": total_general,
        "total_general_guaranies": total_guaranies,
        "liquidacion_iva_5": _text(g_tot, "dIVA5") or "0",
        "liquidacion_iva_10": _text(g_tot, "dIVA10") or "0",
        "total_iva": _text(g_tot, "dTotIVA") or "0",
    }


def _t(name: str) -> str:
    return f"{{{_NS}}}{name}"


def _required(parent: ET.Element, name: str) -> ET.Element:
    found = parent.find(_t(name))
    if found is None:
        raise SifenValidationError(f"documents.kude.missing_element:{name}")
    return found


def _text(parent: ET.Element | None, name: str) -> str | None:
    if parent is None:
        return None
    child = parent.find(_t(name))
    if child is None or child.text is None:
        return None
    cleaned = child.text.strip()
    return cleaned or None
