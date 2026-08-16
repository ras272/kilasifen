"""Legacy platform-admin raw XML example; ERP consumers must use typed routes."""

from __future__ import annotations

import os

import requests


def main() -> None:
    api_url = os.environ.get("KILA_API_URL", "http://localhost:8000")
    api_key = os.environ["KILA_API_KEY"]
    emitter_id = os.environ["KILA_EMITTER_ID"]
    external_id = os.environ.get("KILA_DOC_EXTERNAL_ID", "erp-factura-1001")
    idempotency_key = os.environ.get("KILA_DOC_IDEMPOTENCY_KEY", external_id)

    payload = {
        "external_id": external_id,
        "idempotency_key": idempotency_key,
        "document_type": "factura",
        "payload": {
            "generated_xml": "<rDE/>",
            "doc_id": "01800241355001001000000012026010112345678901",
            "numero_documento": "1001",
            "fecha_emision": "2026-01-01T12:00:00",
            "monto_total": "100000",
            "codigo_seguridad": "123456789",
            "codigo_actividad": "82999",
        },
    }

    response = requests.post(
        f"{api_url}/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": api_key},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()["data"]
    print(f"document_id={data['document']['id']}")
    print(f"job_id={data['job']['id']}")
    print(f"job_status={data['job']['status']}")


if __name__ == "__main__":
    main()

