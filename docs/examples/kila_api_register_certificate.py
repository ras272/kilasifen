"""Example: register and activate a certificate through Kila SIFEN API."""

from __future__ import annotations

import os
from pathlib import Path

import requests


def main() -> None:
    api_url = os.environ.get("KILA_API_URL", "http://localhost:8000")
    api_key = os.environ["KILA_API_KEY"]
    emitter_id = os.environ["KILA_EMITTER_ID"]
    logical_name = os.environ.get("KILA_CERT_NAME", "principal")
    cert_path = Path(os.environ["KILA_CERT_PATH"])
    cert_password = os.environ["KILA_CERT_PASSWORD"]

    with cert_path.open("rb") as certificate_file:
        response = requests.post(
            f"{api_url}/v1/emitters/{emitter_id}/certificates",
            headers={"X-API-Key": api_key},
            data={"logical_name": logical_name, "password": cert_password},
            files={
                "file": (
                    cert_path.name,
                    certificate_file,
                    "application/x-pkcs12",
                )
            },
            timeout=30,
        )
    response.raise_for_status()
    uploaded = response.json()["data"]["certificate"]
    certificate_id = uploaded["id"]
    print(f"uploaded certificate: {certificate_id}")

    activate = requests.post(
        f"{api_url}/v1/emitters/{emitter_id}/certificates/{certificate_id}/activate",
        headers={"X-API-Key": api_key},
        timeout=30,
    )
    activate.raise_for_status()
    print(f"activated certificate: {certificate_id}")


if __name__ == "__main__":
    main()

