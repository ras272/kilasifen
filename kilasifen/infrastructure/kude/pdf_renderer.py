"""Render a SIFEN KuDE PDF (A4 vertical, Formato 1 convencional).

Layout follows Manual Tecnico v150 section 13.4. Spanish only, no
per-tenant branding. The PDF is built from extract_kude_data so the same
structured snapshot powers both the PDF and the JSON endpoint.

MT v150 §13.3 (p. 194) for KuDE of several pages: every page shows its
number over the total ("2/5"), the totals go on the last page and the QR
is printed, at least, on the first page.
"""

from __future__ import annotations

from io import BytesIO
from typing import Iterable

from fpdf import FPDF

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.kude.data_extractor import extract_kude_data
from kilasifen.infrastructure.kude.formatting import (
    GUARANI,
    format_amount,
    format_kude_date,
)
from kilasifen.infrastructure.kude.qr_generator import render_qr_image

# Design tokens ------------------------------------------------------------
INK = (28, 32, 38)  # primary text
MUTED = (108, 117, 130)  # secondary labels
BORDER = (220, 224, 232)  # table borders, dividers
ACCENT = (28, 70, 115)  # deep professional blue
ACCENT_TEXT = (255, 255, 255)
ACCENT_SOFT = (232, 240, 250)  # zebra header / total band
ZEBRA = (247, 249, 252)
WARNING = (176, 36, 36)
WARNING_BG = (252, 232, 232)

# Typography
T_TITLE = 13
T_DOC_NUMBER = 11
T_SECTION = 8.5
T_BODY = 8.5
T_BODY_SMALL = 7.5
T_LABEL = 6.8
T_TOTAL_BIG = 13
T_FOOTER = 7

# Page geometry (mm)
PAGE_W = 210
MARGIN_X = 10
MARGIN_TOP = 10
MARGIN_BOTTOM = 14  # keeps the footer band free of content
FOOTER_Y = -10  # footer band, measured from the bottom edge
CONTENT_W = PAGE_W - 2 * MARGIN_X  # 190
QR_SIZE = 32  # MT v150 §13.8.1: at least 25 mm

# Spacing scale
GAP_XS = 1.2
GAP_S = 2.5
GAP_M = 4
GAP_L = 6

# Line heights
LH_TIGHT = 3.8
LH_BODY = 4.4
LH_ROOMY = 5


class _KudePdf(FPDF):
    """A4 KuDE page whose footer numbers it over the total pages."""

    #: Printed in the footer of the page being closed when it is set; the
    #: renderer sets it right before output, so only the last page shows it.
    closing_notice: str | None = None

    def footer(self) -> None:
        self.set_y(FOOTER_Y)
        self.set_font("Helvetica", "I", T_FOOTER)
        self.set_text_color(*MUTED)
        if self.closing_notice:
            self.set_x(MARGIN_X)
            self.cell(CONTENT_W, 4, _safe(self.closing_notice), align="C")
        self.set_x(MARGIN_X)
        # MT v150 §13.3: page number over the total, e.g. "2/5".
        self.cell(CONTENT_W, 4, f"Página {self.page_no()}/{{nb}}", align="R")
        self.set_text_color(*INK)


def render_kude_pdf(*, document: Document, emitter: Emitter) -> bytes:
    """Build the KuDE PDF for one signed document."""

    data = extract_kude_data(document=document, emitter=emitter)["kude"]

    pdf = _KudePdf(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=MARGIN_BOTTOM)
    pdf.set_margins(left=MARGIN_X, top=MARGIN_TOP, right=MARGIN_X)
    pdf.add_page()
    pdf.set_text_color(*INK)

    _draw_title_bar(pdf, data)
    if data.get("ambiente_warning"):
        _draw_environment_ribbon(pdf, data["ambiente_warning"])
    _draw_emisor_block(pdf, data)
    _section_divider(pdf)
    _draw_general_and_receptor(pdf, data)
    if (
        data.get("documento_asociado")
        or data.get("nota_credito")
        or data.get("nota_debito")
    ):
        _section_divider(pdf)
        _draw_associated_section(pdf, data)
    _section_divider(pdf)
    # MT v150 §13.3: the QR goes, at least, on the first page, so it is
    # drawn before the items, which may take several pages.
    _draw_consulta_qr(pdf, data)
    _section_divider(pdf)
    _draw_items_table(pdf, data)
    _draw_totals_block(pdf, data)
    pdf.closing_notice = _CLOSING_NOTICE

    raw = pdf.output()
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return raw.encode("latin-1")


# ---------- Title bar -----------------------------------------------------


def _draw_title_bar(pdf: FPDF, data: dict) -> None:
    timbrado = data["timbrado"]
    bar_h = 9
    y = pdf.get_y()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(MARGIN_X, y, CONTENT_W, bar_h, style="F")

    pdf.set_text_color(*ACCENT_TEXT)
    # Left: title
    pdf.set_xy(MARGIN_X + 3, y + 1.6)
    pdf.set_font("Helvetica", "B", T_TITLE)
    pdf.cell(CONTENT_W * 0.65, bar_h - 3, _safe(data["tipo_label"]), align="L")
    # Right: document number
    pdf.set_xy(MARGIN_X + CONTENT_W * 0.5, y + 1.8)
    pdf.set_font("Helvetica", "B", T_DOC_NUMBER)
    pdf.cell(
        CONTENT_W * 0.5 - 3,
        bar_h - 3,
        f"Nº {_safe(timbrado['numero_documento'])}",
        align="R",
    )
    pdf.set_text_color(*INK)
    pdf.set_y(y + bar_h + GAP_S)


# ---------- Environment warning ribbon ------------------------------------


def _draw_environment_ribbon(pdf: FPDF, warning: str) -> None:
    bar_h = 5.5
    y = pdf.get_y()
    pdf.set_fill_color(*WARNING_BG)
    pdf.rect(MARGIN_X, y, CONTENT_W, bar_h, style="F")
    pdf.set_text_color(*WARNING)
    pdf.set_font("Helvetica", "B", T_BODY_SMALL)
    pdf.set_xy(MARGIN_X, y + 0.7)
    pdf.cell(CONTENT_W, bar_h - 1.2, _safe(warning), align="C")
    pdf.set_text_color(*INK)
    pdf.set_y(y + bar_h + GAP_S)


# ---------- Emisor block --------------------------------------------------


def _draw_emisor_block(pdf: FPDF, data: dict) -> None:
    emisor = data["emisor"]
    timbrado = data["timbrado"]
    actividad = emisor.get("actividad_economica") or {}

    top = pdf.get_y()
    left_x = MARGIN_X
    left_w = CONTENT_W * 0.62
    right_x = MARGIN_X + left_w + 4
    right_w = CONTENT_W - left_w - 4

    # Logo placeholder (left strip)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.2)
    pdf.rect(left_x, top, 22, 22)
    pdf.set_xy(left_x, top + 9)
    pdf.set_font("Helvetica", "I", T_LABEL)
    pdf.set_text_color(*MUTED)
    pdf.cell(22, 4, "LOGO", align="C")
    pdf.set_text_color(*INK)

    # Emisor info (next to logo)
    info_x = left_x + 25
    info_w = left_w - 25
    pdf.set_xy(info_x, top)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(info_w, LH_BODY, _safe(emisor["razon_social"]), new_x="LEFT", new_y="NEXT")
    pdf.set_x(info_x)
    pdf.set_font("Helvetica", "", T_BODY_SMALL)
    if emisor.get("nombre_fantasia"):
        pdf.cell(
            info_w,
            LH_TIGHT,
            _safe(emisor["nombre_fantasia"]),
            new_x="LEFT",
            new_y="NEXT",
        )
        pdf.set_x(info_x)
    if actividad.get("descripcion"):
        pdf.set_text_color(*MUTED)
        pdf.cell(
            info_w,
            LH_TIGHT,
            _safe(actividad["descripcion"]),
            new_x="LEFT",
            new_y="NEXT",
        )
        pdf.set_text_color(*INK)
        pdf.set_x(info_x)
    address_bits = []
    if emisor.get("direccion"):
        address_bits.append(_safe(emisor["direccion"]))
    if emisor.get("ciudad"):
        address_bits.append(_safe(emisor["ciudad"]))
    if address_bits:
        pdf.cell(info_w, LH_TIGHT, " · ".join(address_bits), new_x="LEFT", new_y="NEXT")
        pdf.set_x(info_x)
    contact_bits: list[str] = []
    if emisor.get("telefono"):
        contact_bits.append(f"Tel: {_safe(emisor['telefono'])}")
    if emisor.get("email"):
        contact_bits.append(_safe(emisor["email"]))
    if contact_bits:
        pdf.set_text_color(*MUTED)
        pdf.cell(info_w, LH_TIGHT, " · ".join(contact_bits), new_x="LEFT", new_y="NEXT")
        pdf.set_text_color(*INK)

    # Right column: timbrado + RUC
    pdf.set_xy(right_x, top)
    _draw_kv_row(pdf, "RUC", emisor["ruc_dv"], right_w, value_bold=True, value_size=10)
    pdf.set_x(right_x)
    _draw_kv_row(pdf, "Timbrado", timbrado["numero"], right_w)
    pdf.set_x(right_x)
    # NT 10 §1.11: C008 prints as DD-MM-AAAA in the KuDE.
    _draw_kv_row(
        pdf,
        "Inicio vigencia",
        format_kude_date(timbrado["fecha_inicio_vigencia"]),
        right_w,
    )
    if timbrado.get("fecha_fin_vigencia"):
        # C009 only exists in pre-v150 XML (DE_v150.xsd comments it out).
        pdf.set_x(right_x)
        _draw_kv_row(
            pdf,
            "Fin vigencia",
            format_kude_date(timbrado["fecha_fin_vigencia"]),
            right_w,
        )
    pdf.set_x(right_x)
    _draw_kv_row(pdf, "Tipo", timbrado["tipo_documento_label"], right_w)

    # Ensure y is below the tallest column
    pdf.set_y(max(pdf.get_y(), top + 22 + GAP_XS))


# ---------- Generales + receptor in two columns ---------------------------


def _draw_general_and_receptor(pdf: FPDF, data: dict) -> None:
    g = data["datos_generales"]
    r = data["receptor"]

    top = pdf.get_y()
    half = (CONTENT_W - GAP_M) / 2

    _draw_section_label(pdf, "Datos de la operación", x=MARGIN_X, w=half, y=top)
    pdf.set_xy(MARGIN_X, pdf.get_y())
    _draw_kv_row(pdf, "Fecha", _format_datetime(g["fecha_emision"]), half)
    pdf.set_x(MARGIN_X)
    if g.get("condicion_operacion_label"):
        _draw_kv_row(pdf, "Condición", g["condicion_operacion_label"], half)
        pdf.set_x(MARGIN_X)
    if g.get("cantidad_cuotas"):
        _draw_kv_row(pdf, "Cuotas", str(g["cantidad_cuotas"]), half)
        pdf.set_x(MARGIN_X)
    moneda_text = f"{_safe(g['moneda'])} ({_safe(g['moneda_label'])})"
    _draw_kv_row(pdf, "Moneda", moneda_text, half)
    pdf.set_x(MARGIN_X)
    if g.get("tipo_cambio"):
        _draw_kv_row(pdf, "T. cambio", g["tipo_cambio"], half)
        pdf.set_x(MARGIN_X)
    if g.get("tipo_transaccion_label"):
        _draw_kv_row(pdf, "Operación", g["tipo_transaccion_label"], half)

    left_bottom = pdf.get_y()

    # Right column - receptor
    right_x = MARGIN_X + half + GAP_M
    _draw_section_label(pdf, "Receptor", x=right_x, w=half, y=top)
    pdf.set_xy(right_x, top + 4)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.cell(half, LH_BODY, _safe(r["razon_social"]), new_x="LEFT", new_y="NEXT")
    pdf.set_x(right_x)
    pdf.set_font("Helvetica", "", T_BODY_SMALL)
    if r.get("ruc_dv"):
        _draw_kv_row(pdf, "RUC", r["ruc_dv"], half, value_bold=True)
        pdf.set_x(right_x)
    elif r.get("numero_documento_identidad"):
        label = _humanize_id_type(r.get("tipo_documento_identidad")) or "Documento"
        _draw_kv_row(pdf, label, r["numero_documento_identidad"], half)
        pdf.set_x(right_x)
    if r.get("direccion"):
        _draw_kv_row(pdf, "Dirección", r["direccion"], half)
        pdf.set_x(right_x)
    contact_bits: list[str] = []
    if r.get("telefono"):
        contact_bits.append(f"Tel: {_safe(r['telefono'])}")
    if r.get("email"):
        contact_bits.append(_safe(r["email"]))
    if contact_bits:
        _draw_kv_row(pdf, "Contacto", " · ".join(contact_bits), half)

    right_bottom = pdf.get_y()
    pdf.set_y(max(left_bottom, right_bottom) + GAP_XS)


# ---------- Documento asociado / motivo NC --------------------------------


def _draw_associated_section(pdf: FPDF, data: dict) -> None:
    asoc = data.get("documento_asociado")
    nc = data.get("nota_credito") or data.get("nota_debito")
    half = (CONTENT_W - GAP_M) / 2
    top = pdf.get_y()
    right_x = MARGIN_X + half + GAP_M

    if asoc:
        _draw_section_label(pdf, "Documento asociado", x=MARGIN_X, w=half, y=top)
        pdf.set_xy(MARGIN_X, top + 4)
        pdf.set_font("Helvetica", "", T_BODY_SMALL)
        if asoc["tipo"] == "electronico" and asoc.get("cdc"):
            pdf.set_font("Helvetica", "", T_LABEL)
            pdf.set_text_color(*MUTED)
            pdf.cell(half, LH_TIGHT, "CDC", new_x="LEFT", new_y="NEXT")
            pdf.set_x(MARGIN_X)
            pdf.set_text_color(*INK)
            pdf.set_font("Helvetica", "B", T_BODY_SMALL)
            pdf.cell(
                half,
                LH_TIGHT,
                _format_cdc_compact(asoc["cdc"]),
                new_x="LEFT",
                new_y="NEXT",
            )
        elif asoc["tipo"] == "impreso":
            pdf.set_x(MARGIN_X)
            line = (
                f"Timbrado {_safe(asoc.get('timbrado'))}  Nº "
                f"{_safe(asoc.get('establecimiento'))}-"
                f"{_safe(asoc.get('punto'))}-"
                f"{_safe(asoc.get('numero'))}"
            )
            pdf.cell(half, LH_TIGHT, line, new_x="LEFT", new_y="NEXT")
            pdf.set_x(MARGIN_X)
            if asoc.get("fecha_emision"):
                _draw_kv_row(pdf, "Fecha", asoc["fecha_emision"], half)

    left_bottom = pdf.get_y()

    if nc:
        _draw_section_label(pdf, "Motivo de emisión", x=right_x, w=half, y=top)
        pdf.set_xy(right_x, top + 4)
        pdf.set_font("Helvetica", "B", T_BODY_SMALL)
        pdf.cell(half, LH_BODY, _safe(nc["motivo_label"]), new_x="LEFT", new_y="NEXT")

    right_bottom = pdf.get_y()
    pdf.set_y(max(left_bottom, right_bottom) + GAP_XS)


# ---------- Items table ---------------------------------------------------

_ITEM_HEADERS = [
    "Cód.",
    "Descripción",
    "Un.",
    "Cant.",
    "P. Unit.",
    "Desc.",
    "Exentas",
    "5%",
    "10%",
]
_ITEM_WIDTHS = [16, 50, 12, 14, 22, 16, 18, 18, 24]
_ITEM_ALIGNS = ["L", "L", "C", "R", "R", "R", "R", "R", "R"]


_ITEM_HEADER_H = 5.5
_ITEM_ROW_H = 4.8
#: P. Unit., Desc., Exentas, 5% and 10%.
_ITEM_AMOUNT_COLUMNS = frozenset({4, 5, 6, 7, 8})


def _draw_items_table(pdf: FPDF, data: dict) -> None:
    items = data["items"]
    # Item amounts are in the currency of the operation (D015).
    moneda = data["datos_generales"]["moneda"]
    _draw_section_label(pdf, "Detalle", x=MARGIN_X, w=CONTENT_W, y=pdf.get_y())
    pdf.set_y(pdf.get_y() + 0.5)
    _draw_items_header(pdf)

    for index, item in enumerate(items):
        if not _fits(pdf, _ITEM_ROW_H):
            # Break between rows, never inside one, and repeat the header.
            pdf.add_page()
            _draw_items_header(pdf)
        zebra = index % 2 == 1
        if zebra:
            pdf.set_fill_color(*ZEBRA)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.set_x(MARGIN_X)
        cells = [
            item.get("codigo") or "",
            item.get("descripcion") or "",
            item.get("unidad_medida", {}).get("label")
            or item.get("unidad_medida", {}).get("codigo")
            or "",
            item.get("cantidad") or "",
            format_amount(item.get("precio_unitario"), moneda),
            format_amount(item.get("descuento"), moneda),
            format_amount(item.get("valor_exento"), moneda),
            format_amount(item.get("valor_5"), moneda),
            format_amount(item.get("valor_10"), moneda),
        ]
        for column, (value, width, align) in enumerate(
            zip(cells, _ITEM_WIDTHS, _ITEM_ALIGNS, strict=True)
        ):
            text = _safe(value)
            if column in _ITEM_AMOUNT_COLUMNS:
                # Amounts are never cut: a long one prints smaller instead.
                _set_font_to_fit(pdf, text, width, size=T_BODY_SMALL)
            else:
                text = _truncate(text, width)
            pdf.cell(width, _ITEM_ROW_H, text, border="B", align=align, fill=True)
            pdf.set_font("Helvetica", "", T_BODY_SMALL)
        pdf.ln(_ITEM_ROW_H)

    pdf.ln(GAP_S)


def _draw_items_header(pdf: FPDF) -> None:
    pdf.set_fill_color(*ACCENT)
    pdf.set_text_color(*ACCENT_TEXT)
    pdf.set_font("Helvetica", "B", T_LABEL + 0.5)
    pdf.set_x(MARGIN_X)
    for header, width, align in zip(
        _ITEM_HEADERS, _ITEM_WIDTHS, _ITEM_ALIGNS, strict=True
    ):
        pdf.cell(
            width,
            _ITEM_HEADER_H,
            header,
            fill=True,
            align=align if align != "L" else "C",
        )
    pdf.ln(_ITEM_HEADER_H)

    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", T_BODY_SMALL)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.15)


# ---------- Totals block --------------------------------------------------


_TOTALS_BLOCK_W = 78
_TOTALS_LABEL_W = 44
_TOTAL_BAND_H = 8.5


def _draw_totals_block(pdf: FPDF, data: dict) -> None:
    t = data["totales"]
    # F002-F017 and F014 are in the currency of the operation (D015).
    moneda = data["datos_generales"]["moneda"]

    rows = [
        ("Subtotal exentas", t["subtotal_exentas"]),
        ("Subtotal 5%", t["subtotal_5"]),
        ("Subtotal 10%", t["subtotal_10"]),
        ("Total operación", t["total_operacion"]),
        ("Liquidación IVA 5%", t["liquidacion_iva_5"]),
        ("Liquidación IVA 10%", t["liquidacion_iva_10"]),
        ("Total IVA", t["total_iva"]),
    ]
    bands = _total_bands(t, moneda)
    # MT v150 §13.3: the totals go on the last page, so the block is never
    # split; nothing is drawn after it.
    if not _fits(pdf, len(rows) * LH_BODY + len(bands) * (_TOTAL_BAND_H + 1)):
        pdf.add_page()

    block_x = MARGIN_X + CONTENT_W - _TOTALS_BLOCK_W
    value_w = _TOTALS_BLOCK_W - _TOTALS_LABEL_W
    pdf.set_font("Helvetica", "", T_BODY_SMALL)
    pdf.set_text_color(*INK)
    for label, value in rows:
        pdf.set_x(block_x)
        pdf.set_text_color(*MUTED)
        pdf.cell(_TOTALS_LABEL_W, LH_BODY, _safe(label), align="L")
        pdf.set_text_color(*INK)
        pdf.cell(
            value_w,
            LH_BODY,
            _safe(format_amount(value, moneda)),
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    for label, value in bands:
        _draw_total_band(pdf, label=label, value=value, x=block_x)
    pdf.set_y(pdf.get_y() + GAP_S)


def _total_bands(totales: dict, moneda: str) -> list[tuple[str, str]]:
    """Highlighted totals: the general total and the total in guaranies.

    MT v150 §13.4.3 (p. 196) asks for the "Total en Guaraníes". In PYG it is
    F014 itself; in another currency F014 is printed with its currency and
    the total in guaranies is F023 dTotalGs (NT 08 §1.2), never recomputed.
    """

    general = totales["total_general_operacion"]
    if moneda.strip().upper() == GUARANI:
        return [("TOTAL EN GUARANÍES", format_amount(general, GUARANI))]
    bands = [(f"TOTAL {moneda}", format_amount(general, moneda))]
    if totales.get("total_general_guaranies"):
        bands.append(
            (
                "TOTAL EN GUARANÍES",
                format_amount(totales["total_general_guaranies"], GUARANI),
            )
        )
    return bands


def _draw_total_band(pdf: FPDF, *, label: str, value: str, x: float) -> None:
    value_w = _TOTALS_BLOCK_W - _TOTALS_LABEL_W
    y = pdf.get_y() + 1
    pdf.set_fill_color(*ACCENT)
    pdf.rect(x, y, _TOTALS_BLOCK_W, _TOTAL_BAND_H, style="F")
    pdf.set_text_color(*ACCENT_TEXT)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_xy(x + 2, y + 1.7)
    pdf.cell(_TOTALS_LABEL_W - 2, _TOTAL_BAND_H - 3, _safe(label), align="L")
    pdf.set_xy(x + _TOTALS_LABEL_W, y + 1.2)
    _set_font_to_fit(pdf, _safe(value), value_w - 2, style="B", size=T_TOTAL_BIG)
    pdf.cell(value_w - 2, _TOTAL_BAND_H - 2, _safe(value), align="R")
    pdf.set_text_color(*INK)
    pdf.set_y(y + _TOTAL_BAND_H)


# ---------- Consulta + QR -------------------------------------------------


def _draw_consulta_qr(pdf: FPDF, data: dict) -> None:
    qr_url = (data.get("qr") or {}).get("url")
    portal = data["consulta_publica"]["portal_url"]
    cdc_groups = " ".join(data["cdc"]["groups"])

    top = pdf.get_y()
    qr_size = QR_SIZE
    qr_x = MARGIN_X
    info_x = MARGIN_X + qr_size + 5
    info_w = CONTENT_W - qr_size - 5

    if qr_url:
        png = render_qr_image(qr_url, box_size=4)
        pdf.image(BytesIO(png), x=qr_x, y=top, w=qr_size, h=qr_size)
    else:
        pdf.set_draw_color(*BORDER)
        pdf.rect(qr_x, top, qr_size, qr_size)

    pdf.set_xy(info_x, top)
    _label_caps(pdf, "Código de Control (CDC)")
    pdf.set_x(info_x)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(info_w, LH_BODY, cdc_groups, new_x="LEFT", new_y="NEXT")
    pdf.set_x(info_x)
    pdf.ln(GAP_XS)

    pdf.set_x(info_x)
    _label_caps(pdf, "Verificar en")
    pdf.set_x(info_x)
    pdf.set_font("Helvetica", "", T_BODY_SMALL)
    pdf.cell(info_w, LH_BODY, _safe(portal), new_x="LEFT", new_y="NEXT")

    bottom = max(pdf.get_y(), top + qr_size)
    pdf.set_y(bottom + GAP_S)


_CLOSING_NOTICE = "Información Fiscal Auxiliar - SIFEN PARAGUAY"


# ---------- Helpers -------------------------------------------------------


def _draw_section_label(pdf: FPDF, label: str, *, x: float, w: float, y: float) -> None:
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "B", T_SECTION)
    pdf.set_text_color(*ACCENT)
    pdf.cell(w, 4, _safe(label).upper(), new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(*INK)


def _draw_kv_row(
    pdf: FPDF,
    label: str,
    value: str | None,
    total_w: float,
    *,
    value_bold: bool = False,
    value_size: float = T_BODY_SMALL,
) -> None:
    if value is None:
        value = ""
    label_w = min(22, total_w * 0.32)
    value_w = total_w - label_w
    pdf.set_font("Helvetica", "", T_LABEL)
    pdf.set_text_color(*MUTED)
    pdf.cell(label_w, LH_BODY, _safe(label), align="L")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B" if value_bold else "", value_size)
    pdf.cell(
        value_w,
        LH_BODY,
        _truncate(_safe(value), value_w),
        align="L",
        new_x="LMARGIN",
        new_y="NEXT",
    )


def _label_caps(pdf: FPDF, label: str) -> None:
    pdf.set_font("Helvetica", "B", T_LABEL)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 3.2, _safe(label).upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)


def _set_font_to_fit(
    pdf: FPDF, text: str, width: float, *, style: str = "", size: float
) -> None:
    """Use Helvetica at ``size``, or smaller (down to 5 pt) until ``text`` fits."""

    pdf.set_font("Helvetica", style, size)
    padding = 2 * pdf.c_margin
    while size > 5 and pdf.get_string_width(text) + padding > width:
        size -= 0.5
        pdf.set_font("Helvetica", style, size)


def _fits(pdf: FPDF, height: float) -> bool:
    return pdf.get_y() + height <= pdf.page_break_trigger


def _section_divider(pdf: FPDF) -> None:
    y = pdf.get_y() + 0.5
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN_X, y, MARGIN_X + CONTENT_W, y)
    pdf.set_y(y + GAP_S)


def _format_datetime(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    if "T" in text:
        date_part, time_part = text.split("T", 1)
        time_part = time_part.split("+", 1)[0].split(".", 1)[0]
        return f"{date_part} {time_part}"
    return text


def _format_cdc_compact(cdc: str) -> str:
    raw = "".join(ch for ch in str(cdc) if ch.isdigit())
    if len(raw) != 44:
        return _safe(cdc)
    return " ".join(raw[i : i + 4] for i in range(0, 44, 4))


def _humanize_id_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("_", " ").title()


def _safe(value) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.encode("latin-1", "replace").decode("latin-1")


def _truncate(text: str, width_mm: float) -> str:
    max_chars = max(3, int(width_mm * 1.7))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "."


__all__: Iterable[str] = ("render_kude_pdf",)
