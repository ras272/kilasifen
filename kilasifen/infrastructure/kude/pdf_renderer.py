"""Render a SIFEN KuDE PDF (A4 vertical, Formato 1 convencional).

Layout follows Manual Tecnico v150 section 13.4. Spanish only, no
per-tenant branding. The PDF is built from extract_kude_data so the same
structured snapshot powers both the PDF and the JSON endpoint.
"""

from __future__ import annotations

from io import BytesIO

from fpdf import FPDF

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.kude.data_extractor import extract_kude_data
from kilasifen.infrastructure.kude.qr_generator import render_qr_image


class _KudePDF(FPDF):
    pass


def render_kude_pdf(*, document: Document, emitter: Emitter) -> bytes:
    """Build the KuDE PDF for one signed document."""

    data = extract_kude_data(document=document, emitter=emitter)["kude"]

    pdf = _KudePDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_margins(left=10, top=10, right=10)

    _draw_header(pdf, data)
    _draw_general_data(pdf, data)
    _draw_receptor(pdf, data)
    if data.get("documento_asociado") or data.get("nota_credito"):
        _draw_associated_section(pdf, data)
    _draw_items(pdf, data)
    _draw_totals(pdf, data)
    _draw_consulta_qr(pdf, data)
    _draw_footer_notice(pdf, data)

    raw = pdf.output()
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return raw.encode("latin-1")


def _draw_header(pdf: _KudePDF, data: dict) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, _safe(data["tipo_label"]), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    emisor = data["emisor"]
    timbrado = data["timbrado"]

    block_top = pdf.get_y()
    # Two columns: emisor (left, ~120mm) | timbrado (right, ~70mm)
    left_x = 10
    right_x = 130
    line_height = 4.5

    pdf.set_xy(left_x, block_top)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(115, line_height, _safe(emisor["razon_social"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    if emisor.get("nombre_fantasia"):
        pdf.cell(115, line_height, _safe(emisor["nombre_fantasia"]), new_x="LMARGIN", new_y="NEXT")
    actividad = emisor.get("actividad_economica") or {}
    if actividad.get("descripcion"):
        pdf.cell(115, line_height, _safe(actividad["descripcion"]), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(115, line_height, _safe(emisor["direccion"]), new_x="LMARGIN", new_y="NEXT")
    if emisor.get("ciudad"):
        pdf.cell(115, line_height, f"Ciudad: {_safe(emisor['ciudad'])}", new_x="LMARGIN", new_y="NEXT")
    if emisor.get("telefono") or emisor.get("email"):
        contact = " | ".join(
            filter(None, [
                f"Tel: {_safe(emisor['telefono'])}" if emisor.get("telefono") else None,
                f"Email: {_safe(emisor['email'])}" if emisor.get("email") else None,
            ])
        )
        pdf.cell(115, line_height, contact, new_x="LMARGIN", new_y="NEXT")

    # Right column
    pdf.set_xy(right_x, block_top)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(70, line_height, f"RUC: {_safe(emisor['ruc_dv'])}", new_x="LEFT", new_y="NEXT")
    pdf.set_x(right_x)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(70, line_height, f"Timbrado N°: {_safe(timbrado['numero'])}", new_x="LEFT", new_y="NEXT")
    pdf.set_x(right_x)
    pdf.cell(
        70, line_height,
        f"Inicio vigencia: {_safe(timbrado['fecha_inicio_vigencia'])}",
        new_x="LEFT", new_y="NEXT",
    )
    if timbrado.get("fecha_fin_vigencia"):
        pdf.set_x(right_x)
        pdf.cell(
            70, line_height,
            f"Fin vigencia: {_safe(timbrado['fecha_fin_vigencia'])}",
            new_x="LEFT", new_y="NEXT",
        )
    pdf.set_x(right_x)
    pdf.set_font("Helvetica", "B", 9)
    label = f"{timbrado['tipo_documento_label']} N° {timbrado['numero_documento']}"
    pdf.cell(70, line_height, _safe(label), new_x="LEFT", new_y="NEXT")
    pdf.ln(3)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)


def _draw_general_data(pdf: _KudePDF, data: dict) -> None:
    g = data["datos_generales"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Datos generales", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    items = [
        f"Fecha de emisión: {_safe(g['fecha_emision'])}",
        f"Condición: {_safe(g.get('condicion_operacion_label') or '')}",
    ]
    if g.get("cantidad_cuotas"):
        items.append(f"Cuotas: {g['cantidad_cuotas']}")
    items.append(f"Moneda: {_safe(g['moneda'])} ({_safe(g['moneda_label'])})")
    if g.get("tipo_cambio"):
        items.append(f"Tipo de cambio: {_safe(g['tipo_cambio'])}")
    if g.get("tipo_transaccion_label"):
        items.append(f"Operación: {_safe(g['tipo_transaccion_label'])}")
    pdf.multi_cell(0, 4.5, "  |  ".join(items))
    pdf.ln(1)


def _draw_receptor(pdf: _KudePDF, data: dict) -> None:
    r = data["receptor"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Datos del receptor", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    if r.get("ruc_dv"):
        identificacion = f"RUC: {_safe(r['ruc_dv'])}"
    elif r.get("numero_documento_identidad"):
        identificacion = (
            f"{_safe(r.get('tipo_documento_identidad') or 'Documento')}: "
            f"{_safe(r['numero_documento_identidad'])}"
        )
    else:
        identificacion = ""
    pdf.cell(0, 4.5, _safe(r["razon_social"]), new_x="LMARGIN", new_y="NEXT")
    if identificacion:
        pdf.cell(0, 4.5, identificacion, new_x="LMARGIN", new_y="NEXT")
    if r.get("direccion"):
        pdf.cell(0, 4.5, f"Dirección: {_safe(r['direccion'])}", new_x="LMARGIN", new_y="NEXT")
    contact = []
    if r.get("telefono"):
        contact.append(f"Tel: {_safe(r['telefono'])}")
    if r.get("email"):
        contact.append(f"Email: {_safe(r['email'])}")
    if contact:
        pdf.cell(0, 4.5, "  |  ".join(contact), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _draw_associated_section(pdf: _KudePDF, data: dict) -> None:
    pdf.set_font("Helvetica", "B", 9)
    asoc = data.get("documento_asociado")
    nc = data.get("nota_credito")
    if asoc:
        pdf.cell(0, 5, "Documento asociado", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        if asoc["tipo"] == "electronico" and asoc.get("cdc"):
            pdf.cell(0, 4.5, f"CDC: {_safe(asoc['cdc'])}", new_x="LMARGIN", new_y="NEXT")
        elif asoc["tipo"] == "impreso":
            line = (
                f"Timbrado {_safe(asoc.get('timbrado'))}  Nº "
                f"{_safe(asoc.get('establecimiento'))}-{_safe(asoc.get('punto'))}-"
                f"{_safe(asoc.get('numero'))}"
            )
            pdf.cell(0, 4.5, line, new_x="LMARGIN", new_y="NEXT")
            if asoc.get("fecha_emision"):
                pdf.cell(0, 4.5, f"Fecha emisión: {_safe(asoc['fecha_emision'])}", new_x="LMARGIN", new_y="NEXT")
    if nc:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, "Motivo de emisión", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 4.5, _safe(nc["motivo_label"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _draw_items(pdf: _KudePDF, data: dict) -> None:
    items = data["items"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Detalle", new_x="LMARGIN", new_y="NEXT")
    headers = ["Cód.", "Descripción", "Unidad", "Cant.", "P. Unit.", "Desc.", "Exentas", "5%", "10%"]
    widths = [16, 50, 14, 14, 22, 16, 18, 18, 22]
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_fill_color(238, 238, 238)
    for header, width in zip(headers, widths, strict=True):
        pdf.cell(width, 5, header, border=1, fill=True, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 7.5)
    for item in items:
        cells = [
            (item["codigo"], "L"),
            (item["descripcion"], "L"),
            (item["unidad_medida"]["label"] or item["unidad_medida"]["codigo"], "C"),
            (item["cantidad"], "R"),
            (item["precio_unitario"] or "", "R"),
            (item["descuento"], "R"),
            (item["valor_exento"], "R"),
            (item["valor_5"], "R"),
            (item["valor_10"], "R"),
        ]
        for (value, align), width in zip(cells, widths, strict=True):
            pdf.cell(width, 4.5, _truncate(_safe(value), width), border=1, align=align)
        pdf.ln(4.5)
    pdf.ln(1)


def _draw_totals(pdf: _KudePDF, data: dict) -> None:
    t = data["totales"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Totales", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    rows = [
        ("Subtotal exentas", t["subtotal_exentas"]),
        ("Subtotal 5%", t["subtotal_5"]),
        ("Subtotal 10%", t["subtotal_10"]),
        ("Total operación", t["total_operacion"]),
        ("Total general (Gs.)", t["total_general_guaranies"]),
        ("Liquidación IVA 5%", t["liquidacion_iva_5"]),
        ("Liquidación IVA 10%", t["liquidacion_iva_10"]),
        ("Total IVA", t["total_iva"]),
    ]
    for label, value in rows:
        pdf.cell(60, 4.5, _safe(label), border=0)
        pdf.cell(40, 4.5, _safe(value), border=0, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _draw_consulta_qr(pdf: _KudePDF, data: dict) -> None:
    qr_url = (data.get("qr") or {}).get("url")
    portal = data["consulta_publica"]["portal_url"]
    cdc_groups = " ".join(data["cdc"]["groups"])

    y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Información de consulta", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 7.5)
    pdf.cell(140, 4.2, f"Portal: {portal}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(140, 4.2, f"CDC: {cdc_groups}", new_x="LMARGIN", new_y="NEXT")

    if qr_url:
        png = render_qr_image(qr_url, box_size=4)
        qr_size = 35
        x = 200 - qr_size - 5
        # Place QR at the same vertical area as the consult info block
        pdf.image(BytesIO(png), x=x, y=y, w=qr_size, h=qr_size)
    pdf.ln(2)


def _draw_footer_notice(pdf: _KudePDF, data: dict) -> None:
    warning = data.get("ambiente_warning")
    if warning:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 5, _safe(warning), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(0, 4, "Información Fiscal Auxiliar - SIFEN PARAGUAY", align="C")


def _safe(value) -> str:
    if value is None:
        return ""
    text = str(value)
    # fpdf2 default core fonts are latin-1 only; replace unsupported chars safely.
    return text.encode("latin-1", "replace").decode("latin-1")


def _truncate(text: str, width_mm: float) -> str:
    # Simple visual cap: ~1.6 chars per mm at 7.5pt Helvetica
    max_chars = max(3, int(width_mm * 1.7))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "."
