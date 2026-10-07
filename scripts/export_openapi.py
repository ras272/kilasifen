"""Export the canonical public OpenAPI contract for the documentation site."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from kilasifen.api.app import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "apps" / "docs" / "public" / "openapi.json"

TAG_METADATA = {
    "health": ("Estado del sistema", "Liveness y readiness de la plataforma."),
    "access administration": (
        "Administración de acceso",
        "Consumidores, credenciales y scopes administrativos.",
    ),
    "auth": ("Autenticación", "Comprobación de credenciales y principal activo."),
    "emitters": ("Emisores", "Configuración y preparación de contribuyentes."),
    "certificates": ("Certificados", "Carga y activación segura de PKCS#12."),
    "stampings": ("Timbrados", "Vigencias y numeración fiscal."),
    "documents": (
        "Documentos",
        "Facturas, notas de crédito y de débito, XML y KuDE.",
    ),
    "events": ("Eventos", "Cancelación e inutilización asíncronas."),
    "queries": ("Consultas", "Consultas de documentos y RUC en SIFEN."),
    "jobs": ("Jobs", "Seguimiento de procesos asíncronos."),
    "webhooks": ("Webhooks", "Endpoints, entregas firmadas y replay."),
}

SUMMARY_TRANSLATIONS = {
    "Health": "Comprobar liveness",
    "Ready": "Comprobar readiness",
    "Create Emitter": "Crear emisor",
    "List Emitters": "Listar emisores",
    "Get Emitter": "Obtener emisor",
    "Update Emitter": "Actualizar emisor",
    "Deactivate Emitter": "Desactivar emisor",
    "Get Emitter Health": "Comprobar preparación del emisor",
    "Upload Certificate": "Cargar certificado",
    "List Certificates": "Listar certificados",
    "Activate Certificate": "Activar certificado",
    "Create Stamping": "Crear timbrado",
    "List Stampings": "Listar timbrados",
    "Activate Stamping": "Activar timbrado",
    "Create a raw document (platform administrators only)": (
        "Crear documento raw (sólo plataforma)"
    ),
    "List Documents": "Listar documentos",
    "Create Factura Document": "Crear factura",
    "Create Nota Credito Document": "Crear nota de crédito",
    "Create Nota Debito Document": "Crear nota de débito",
    "Get Document": "Obtener documento",
    "Get Document Xml": "Descargar XML",
    "Get Document Kude": "Descargar KuDE",
    "Get Document Kude Data": "Obtener datos del KuDE",
    "Get Job": "Obtener job",
    "Retry Job": "Reintentar job",
    "List Jobs": "Listar jobs",
    "Query Ruc": "Consultar RUC en SIFEN",
    "Query Document": "Consultar documento en SIFEN",
    "Reconcile Document": "Reconciliar documento con SIFEN",
    "Create a raw fiscal event (platform administrators only)": (
        "Crear evento raw (sólo plataforma)"
    ),
    "Cancel Document": "Cancelar documento",
    "Inutilize Numbers": "Inutilizar numeración",
    "Get Event": "Obtener evento",
    "Register Webhook Endpoint": "Registrar webhook",
    "List Webhook Endpoints": "Listar webhooks",
    "Update Webhook Endpoint": "Actualizar webhook",
    "Replay Webhook Delivery": "Reprocesar entrega de webhook",
    "Send Webhook Test Event": "Enviar evento de prueba al webhook",
    "Get Webhook Delivery": "Obtener entrega de webhook",
    "List Webhook Deliveries": "Listar entregas de webhook",
    "Create Consumer": "Crear consumidor",
    "Issue Credential": "Emitir credencial",
    "Revoke Credential": "Revocar credencial",
    "Auth Check": "Comprobar autenticación",
}


def build_openapi_schema() -> dict[str, Any]:
    """Build a deterministic, documentation-oriented OpenAPI schema."""

    schema = create_app().openapi()
    schema["info"] = {
        **schema["info"],
        "title": "KilaSifen API",
        "version": "v1",
        "description": (
            "API fiscal multi-tenant para emitir, consultar y conciliar "
            "documentos electrónicos con SIFEN."
        ),
    }
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            summary = operation.get("summary")
            if summary in SUMMARY_TRANSLATIONS:
                operation["summary"] = SUMMARY_TRANSLATIONS[summary]
    used_tags = {
        tag
        for path_item in schema.get("paths", {}).values()
        for operation in path_item.values()
        if isinstance(operation, dict)
        for tag in operation.get("tags", [])
    }
    schema["tags"] = [
        {
            "name": tag,
            "x-displayName": TAG_METADATA.get(tag, (tag.title(), ""))[0],
            "description": TAG_METADATA.get(tag, ("", ""))[1],
        }
        for tag in sorted(used_tags)
    ]
    return schema


def render_openapi_json() -> str:
    """Serialize the canonical schema with stable formatting."""

    return json.dumps(
        build_openapi_schema(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed schema is stale instead of writing it.",
    )
    args = parser.parse_args()
    expected = render_openapi_json()

    if args.check:
        current = (
            args.output.read_text(encoding="utf-8") if args.output.exists() else None
        )
        if current != expected:
            print(
                "OpenAPI export is stale. Run: "
                "python scripts/export_openapi.py"
            )
            return 1
        print(f"OpenAPI export is current: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
