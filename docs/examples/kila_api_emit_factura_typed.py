"""Example: create a typed factura emission job through Kila SIFEN API."""

from __future__ import annotations

import os

import requests


DEFAULT_XML = (
    "<rDE xmlns='http://ekuatia.set.gov.py/sifen/xsd'>"
    "<DE Id='01800123450001001000000012026010112345678901'/>"
    "</rDE>"
)


def main() -> None:
    api_url = os.environ.get("KILA_API_URL", "http://localhost:8000")
    api_key = os.environ["KILA_API_KEY"]
    emitter_id = os.environ["KILA_EMITTER_ID"]
    external_id = os.environ.get("KILA_DOC_EXTERNAL_ID", "erp-factura-typed-1001")
    idempotency_key = os.environ.get("KILA_DOC_IDEMPOTENCY_KEY", external_id)
    generated_xml = os.environ.get("KILA_GENERATED_XML", DEFAULT_XML)
    doc_id = os.environ.get("KILA_DOC_ID", "01800123450001001000000012026010112345678901")

    payload = {
        "external_id": external_id,
        "idempotency_key": idempotency_key,
        "factura": {
            "generated_xml": generated_xml,
            "doc_id": doc_id,
            "establecimiento": 1,
            "punto": "001",
            "numero": 1001,
            "fecha": "2026-04-25T10:00:00",
            "cliente": {
                "ruc": "80069563-1",
                "razonSocial": "TIPS S.A",
            },
            "items": [
                {
                    "codigo": "A-001",
                    "descripcion": "Producto de prueba",
                    "cantidad": 1,
                    "precioUnitario": 100000,
                    "iva": 10,
                }
            ],
        },
    }

    response = requests.post(
        f"{api_url}/v1/emitters/{emitter_id}/documents/facturas",
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
