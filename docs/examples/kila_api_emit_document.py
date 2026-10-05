"""Legacy platform-admin raw XML example; ERP consumers must use typed routes.

The deprecated raw route only accepts an unsigned ``rDE`` that validates
against the official XSD, with ``dVerFor``, one ``DE`` and ``gCamFuFD`` as its
only children. KilaSifen signs that ``DE`` with the emitter certificate and
takes ``doc_id`` from its ``Id``. Point ``KILA_RDE_XML_PATH`` at such a file.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests


def build_request_body(
    *,
    rde_xml: str,
    external_id: str,
    idempotency_key: str,
) -> dict:
    """Build the raw-route body for one unsigned ``rDE``."""

    return {
        "external_id": external_id,
        "idempotency_key": idempotency_key,
        "document_type": "factura",
        "payload": {"generated_xml": rde_xml},
    }


def main() -> None:
    api_url = os.environ.get("KILA_API_URL", "http://localhost:8000")
    api_key = os.environ["KILA_API_KEY"]
    emitter_id = os.environ["KILA_EMITTER_ID"]
    rde_xml = Path(os.environ["KILA_RDE_XML_PATH"]).read_text(encoding="utf-8")
    external_id = os.environ.get("KILA_DOC_EXTERNAL_ID", "erp-factura-1001")
    idempotency_key = os.environ.get("KILA_DOC_IDEMPOTENCY_KEY", external_id)

    response = requests.post(
        f"{api_url}/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": api_key},
        json=build_request_body(
            rde_xml=rde_xml,
            external_id=external_id,
            idempotency_key=idempotency_key,
        ),
        timeout=30,
    )
    if response.status_code == 422:
        error = response.json()["error"]
        raise SystemExit(f"{error['code']}: {error.get('details')}")
    response.raise_for_status()

    data = response.json()["data"]
    print(f"document_id={data['document']['id']}")
    print(f"job_id={data['job']['id']}")
    print(f"job_status={data['job']['status']}")


if __name__ == "__main__":
    main()
