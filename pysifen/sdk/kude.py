"""KuDE helpers: human-readable HTML output for SIFEN documents."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any


def build_kude_context(rde) -> dict[str, Any]:
    """Build a normalized context dict from a parsed RDe object."""
    de = getattr(rde, "DE", None)
    if de is None:
        raise ValueError("RDe object must include DE payload")

    g_timb = getattr(de, "gTimb", None)
    g_gral = getattr(de, "gDatGralOpe", None)
    g_emis = getattr(g_gral, "gEmis", None)
    g_rec = getattr(g_gral, "gDatRec", None)
    g_dtip = getattr(de, "gDtipDE", None)
    g_tot = getattr(de, "gTotSub", None)
    g_fuera = getattr(rde, "gCamFuFD", None)

    items_raw = list(getattr(g_dtip, "gCamItem", []) or [])
    items = []
    for index, item in enumerate(items_raw, start=1):
        valor = getattr(item, "gValorItem", None)
        items.append(
            {
                "nro": index,
                "codigo": _text(getattr(item, "dCodInt", "")),
                "descripcion": _text(getattr(item, "dDesProSer", "")),
                "cantidad": _text(getattr(item, "dCantProSer", "")),
                "precio_unitario": _text(
                    getattr(valor, "dPUniProSer", "")
                ),
                "total": _text(getattr(valor, "dTotOpeItem", "")),
            }
        )

    return {
        "cdc": _text(getattr(de, "Id", "")),
        "tipo_documento": _first_non_empty(
            _text(getattr(g_timb, "dDesTiDE", "")),
            _text(getattr(g_timb, "iTiDE", "")),
        ),
        "numero_documento": "-".join(
            [
                _text(getattr(g_timb, "dEst", "")),
                _text(getattr(g_timb, "dPunExp", "")),
                _text(getattr(g_timb, "dNumDoc", "")),
            ]
        ).strip("-"),
        "fecha_emision": _text(getattr(g_gral, "dFeEmiDE", "")),
        "emisor_nombre": _text(getattr(g_emis, "dNomEmi", "")),
        "emisor_ruc": _join_ruc(
            _text(getattr(g_emis, "dRucEm", "")),
            _text(getattr(g_emis, "dDVEmi", "")),
        ),
        "receptor_nombre": _text(getattr(g_rec, "dNomRec", "")),
        "receptor_id": _first_non_empty(
            _join_ruc(
                _text(getattr(g_rec, "dRucRec", "")),
                _text(getattr(g_rec, "dDVRec", "")),
            ),
            _text(getattr(g_rec, "dNumIDRec", "")),
            _text(getattr(g_rec, "dNumIDVen", "")),
        ),
        "moneda": _text(
            getattr(getattr(g_gral, "gOpeCom", None), "cMoneOpe", "")
        ),
        "total_operacion": _text(getattr(g_tot, "dTotGralOpe", "")),
        "total_iva": _text(getattr(g_tot, "dTotIVA", "")),
        "cantidad_items": str(len(items)),
        "qr_url": _text(getattr(g_fuera, "dCarQR", "")),
        "items": items,
    }


def render_kude_html(rde, *, title: str = "KuDE") -> str:
    """Render a printable KuDE HTML from an RDe object."""
    ctx = build_kude_context(rde)
    rows = "\n".join(
        [
            (
                "<tr>"
                f"<td>{item['nro']}</td>"
                f"<td>{_h(item['codigo'])}</td>"
                f"<td>{_h(item['descripcion'])}</td>"
                f"<td>{_h(item['cantidad'])}</td>"
                f"<td>{_h(item['precio_unitario'])}</td>"
                f"<td>{_h(item['total'])}</td>"
                "</tr>"
            )
            for item in ctx["items"]
        ]
    )
    if not rows:
        rows = (
            '<tr><td colspan="6" class="muted">'
            "Sin items cargados"
            "</td></tr>"
        )

    qr_section = ""
    if ctx["qr_url"]:
        qr_section = (
            '<div class="card">'
            "<h2>Consulta QR</h2>"
            f'<p><a href="{_h(ctx["qr_url"])}">{_h(ctx["qr_url"])}</a></p>'
            "</div>"
        )

    return (
        "<!doctype html>"
        "<html lang='es'>"
        "<head>"
        "<meta charset='utf-8' />"
        "<meta name='viewport' "
        "content='width=device-width, initial-scale=1' />"
        f"<title>{_h(title)} - {_h(ctx['numero_documento'])}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:0;padding:24px;"
        "background:#f7f7f7;color:#111;}"
        ".sheet{max-width:980px;margin:0 auto;background:#fff;"
        "border:1px solid #ddd;border-radius:12px;padding:24px;}"
        "h1{margin:0 0 12px;font-size:28px;}"
        "h2{margin:0 0 8px;font-size:18px;}"
        ".grid{display:grid;"
        "grid-template-columns:repeat(auto-fit,minmax(240px,1fr));"
        "gap:12px;margin-bottom:16px;}"
        ".card{border:1px solid #e0e0e0;border-radius:10px;padding:12px;}"
        ".k{font-size:12px;color:#666;text-transform:uppercase;"
        "letter-spacing:.04em;}"
        ".v{font-size:14px;font-weight:600;word-break:break-word;}"
        "table{width:100%;border-collapse:collapse;margin-top:8px;}"
        "th,td{border:1px solid #e5e5e5;padding:8px;text-align:left;"
        "font-size:13px;}"
        "th{background:#f4f6f8;}"
        ".tot{display:grid;grid-template-columns:repeat(2,minmax(180px,1fr));"
        "gap:12px;margin-top:16px;}"
        ".muted{color:#666;}"
        "a{color:#0b57d0;text-decoration:none;}"
        "a:hover{text-decoration:underline;}"
        "@media print{body{padding:0;background:#fff;}.sheet{border:none;"
        "border-radius:0;"
        "padding:0;max-width:none;}}"
        "</style>"
        "</head>"
        "<body>"
        "<div class='sheet'>"
        f"<h1>{_h(title)}</h1>"
        "<div class='grid'>"
        f"{_pair('CDC', ctx['cdc'])}"
        f"{_pair('Tipo', ctx['tipo_documento'])}"
        f"{_pair('Numero', ctx['numero_documento'])}"
        f"{_pair('Fecha emision', ctx['fecha_emision'])}"
        f"{_pair('Emisor', ctx['emisor_nombre'])}"
        f"{_pair('RUC emisor', ctx['emisor_ruc'])}"
        f"{_pair('Receptor', ctx['receptor_nombre'])}"
        f"{_pair('Id receptor', ctx['receptor_id'])}"
        "</div>"
        "<div class='card'>"
        "<h2>Detalle de items</h2>"
        "<table>"
        "<thead><tr><th>#</th><th>Codigo</th><th>Descripcion</th>"
        "<th>Cantidad</th><th>Precio unitario</th><th>Total</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</div>"
        "<div class='tot'>"
        f"{_pair('Moneda', ctx['moneda'])}"
        f"{_pair('Cantidad items', ctx['cantidad_items'])}"
        f"{_pair('Total operacion', ctx['total_operacion'])}"
        f"{_pair('Total IVA', ctx['total_iva'])}"
        "</div>"
        f"{qr_section}"
        "</div>"
        "</body>"
        "</html>"
    )


def render_kude_html_from_xml(
    xml_string: str, *, title: str = "KuDE"
) -> str:
    """Parse an RDe XML and render KuDE HTML."""
    from pysifen.de.bindings.v150.fe_v141 import RDe

    rde = RDe.from_xml(xml_string)
    return render_kude_html(rde, title=title)


def save_kude_html(
    rde,
    file_path: str | Path,
    *,
    title: str = "KuDE",
    encoding: str = "utf-8",
) -> Path:
    """Render and persist KuDE HTML, returning the written path."""
    path = Path(file_path)
    html = render_kude_html(rde, title=title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding=encoding)
    return path


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _join_ruc(ruc: str, dv: str) -> str:
    if not ruc:
        return ""
    if dv:
        return f"{ruc}-{dv}"
    return ruc


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _h(value: str) -> str:
    return escape(value, quote=True)


def _pair(key: str, value: str) -> str:
    return (
        "<div class='card'>"
        f"<div class='k'>{_h(key)}</div>"
        f"<div class='v'>{_h(value) or '&nbsp;'}</div>"
        "</div>"
    )
