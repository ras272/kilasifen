"""E2E smoke test for Kila SIFEN API.

This script validates the operational path end-to-end:

1. API liveness/readiness
2. Emitter availability
3. Active certificate and active stamping
4. Document creation and job processing convergence
5. Optional webhook test-event flow

It prints explicit PASS/FAIL output and exits with non-zero code on failure.
Because it exercises the deprecated raw XML route, its credential must be a
platform-admin bootstrap key. ERP parity tests should use the typed examples.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from lxml import etree

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "retry_scheduled"}
TERMINAL_DELIVERY_STATUSES = {"delivered", "failed", "retry_pending"}


class SmokeFailure(RuntimeError):
    """Raised when one smoke check fails."""


@dataclass(slots=True)
class CheckResult:
    """Result from one smoke step."""

    name: str
    ok: bool
    detail: str


class KilaApiClient:
    """Small HTTP wrapper around the Kila API contract."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: int):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    def get(self, path: str, expected_status: int = 200) -> dict[str, Any]:
        return self._request("GET", path, expected_status=expected_status)

    def post(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expected_statuses: tuple[int, ...] = (200, 201),
    ) -> dict[str, Any]:
        expected_status = expected_statuses[0]
        return self._request(
            "POST",
            path,
            payload=payload,
            expected_status=expected_status,
            expected_statuses=expected_statuses,
        )

    def post_multipart(
        self,
        path: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, Any, str]],
        expected_status: int = 201,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"X-API-Key": self.headers["X-API-Key"]}
        response = self.session.post(
            url,
            headers=headers,
            data=data,
            files=files,
            timeout=self.timeout_seconds,
        )
        return self._normalize_response(
            response=response,
            method="POST",
            path=path,
            expected_status=expected_status,
            expected_statuses=(expected_status,),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expected_status: int,
        expected_statuses: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.session.request(
            method,
            url,
            headers=self.headers,
            data=json.dumps(payload) if payload is not None else None,
            timeout=self.timeout_seconds,
        )
        return self._normalize_response(
            response=response,
            method=method,
            path=path,
            expected_status=expected_status,
            expected_statuses=expected_statuses or (expected_status,),
        )

    def _normalize_response(
        self,
        *,
        response: requests.Response,
        method: str,
        path: str,
        expected_status: int,
        expected_statuses: tuple[int, ...],
    ) -> dict[str, Any]:
        if response.status_code not in expected_statuses:
            snippet = response.text[:600]
            raise SmokeFailure(
                (
                    f"{method} {path} returned {response.status_code}, expected "
                    f"{expected_statuses}. Body: {snippet}"
                )
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SmokeFailure(f"{method} {path} returned non-JSON payload.") from exc

        if "error" in payload:
            raise SmokeFailure(
                f"{method} {path} returned error envelope: {payload['error']}"
            )
        if "data" not in payload:
            raise SmokeFailure(f"{method} {path} missing data envelope.")
        return payload["data"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run end-to-end smoke checks against Kila SIFEN API.",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("KILA_API_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("KILA_API_KEY"),
        help="API key for X-API-Key header (or KILA_API_KEY env).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.getenv("KILA_SMOKE_TIMEOUT_SECONDS", "30")),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=int(os.getenv("KILA_SMOKE_POLL_INTERVAL_SECONDS", "2")),
    )
    parser.add_argument(
        "--job-timeout-seconds",
        type=int,
        default=int(os.getenv("KILA_SMOKE_JOB_TIMEOUT_SECONDS", "180")),
    )
    parser.add_argument(
        "--require-approved",
        action="store_true",
        help="Fail if document terminal status is not approved.",
    )
    parser.add_argument(
        "--emitter-id",
        default=os.getenv("KILA_EMITTER_ID"),
    )
    parser.add_argument(
        "--emitter-ruc",
        default=os.getenv("KILA_EMITTER_RUC", "80024135"),
    )
    parser.add_argument(
        "--emitter-dv",
        default=os.getenv("KILA_EMITTER_DV", "5"),
    )
    parser.add_argument(
        "--emitter-legal-name",
        default=os.getenv("KILA_EMITTER_LEGAL_NAME", "ARES PARAGUAY SRL"),
    )
    parser.add_argument(
        "--emitter-tax-environment",
        default=os.getenv("KILA_EMITTER_TAX_ENVIRONMENT", "test"),
    )
    parser.add_argument(
        "--emitter-csc",
        default=os.getenv("KILA_EMITTER_CSC", "ABCD0000000000000000000000000000"),
    )
    parser.add_argument(
        "--emitter-csc-id",
        default=os.getenv("KILA_EMITTER_CSC_ID", "0001"),
    )
    parser.add_argument(
        "--cert-path",
        default=os.getenv("KILA_CERT_PATH"),
    )
    parser.add_argument(
        "--cert-password",
        default=os.getenv("KILA_CERT_PASSWORD"),
    )
    parser.add_argument(
        "--cert-logical-name",
        default=os.getenv("KILA_CERT_LOGICAL_NAME", "smoke"),
    )
    parser.add_argument(
        "--timbrado-number",
        default=os.getenv("KILA_TIMBRADO_NUMBER"),
    )
    parser.add_argument(
        "--timbrado-start-date",
        default=os.getenv("KILA_TIMBRADO_START_DATE"),
        help="YYYY-MM-DD (required only when script needs to create a stamping).",
    )
    parser.add_argument(
        "--document-type",
        default=os.getenv("KILA_DOCUMENT_TYPE", "factura"),
    )
    parser.add_argument(
        "--document-xml-path",
        default=os.getenv("KILA_DOCUMENT_XML_PATH"),
        help="If omitted, XML is generated from docs/examples/send_ares_factura_test.py",
    )
    parser.add_argument(
        "--webhook-endpoint-id",
        default=os.getenv("KILA_WEBHOOK_ENDPOINT_ID"),
        help="Optional: if provided, sends a signed webhook.test event too.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.api_key:
        print("FAIL: --api-key (or KILA_API_KEY) is required.")
        return 1

    client = KilaApiClient(
        base_url=args.api_url,
        api_key=args.api_key,
        timeout_seconds=args.timeout_seconds,
    )
    checks: list[CheckResult] = []

    try:
        run_check(checks, "health", lambda: check_health(client))
        run_check(checks, "ready", lambda: check_ready(client))

        emitter_id = args.emitter_id
        if emitter_id:
            run_check(
                checks,
                "emitter_exists",
                lambda: check_emitter_exists(client, emitter_id),
            )
        else:
            emitter_id = create_smoke_emitter(client, args)
            checks.append(
                CheckResult(
                    name="emitter_create",
                    ok=True,
                    detail=f"created emitter_id={emitter_id}",
                )
            )

        run_check(
            checks,
            "certificate_active",
            lambda: ensure_active_certificate(client, args, emitter_id),
        )
        run_check(
            checks,
            "stamping_active",
            lambda: ensure_active_stamping(client, args, emitter_id),
        )

        payload, external_id, idempotency_key = build_document_payload(args)
        document_data = client.post(
            f"/v1/emitters/{emitter_id}/documents",
            payload={
                "external_id": external_id,
                "idempotency_key": idempotency_key,
                "document_type": args.document_type,
                "payload": payload,
            },
            expected_statuses=(200, 201),
        )
        document_id = document_data["document"]["id"]
        job_id = document_data["job"]["id"]
        checks.append(
            CheckResult(
                name="document_create",
                ok=True,
                detail=f"document_id={document_id} job_id={job_id}",
            )
        )

        terminal_job = poll_job_until_terminal(
            client,
            job_id=job_id,
            timeout_seconds=args.job_timeout_seconds,
            interval_seconds=args.poll_interval_seconds,
        )
        checks.append(
            CheckResult(
                name="job_converged",
                ok=True,
                detail=f"job_status={terminal_job['status']} attempts={terminal_job['attempts']}",
            )
        )

        document_state = client.get(f"/v1/documents/{document_id}")["document"]
        validate_document_terminal_state(
            document=document_state,
            job=terminal_job,
            require_approved=args.require_approved,
        )
        checks.append(
            CheckResult(
                name="document_terminal_state",
                ok=True,
                detail=(
                    f"internal_status={document_state['internal_status']} "
                    f"sifen_code={document_state.get('sifen_result_code')}"
                ),
            )
        )

        if args.webhook_endpoint_id:
            run_check(
                checks,
                "webhook_test_event",
                lambda: run_webhook_smoke(
                    client=client,
                    emitter_id=emitter_id,
                    endpoint_id=args.webhook_endpoint_id,
                    timeout_seconds=args.job_timeout_seconds,
                    interval_seconds=args.poll_interval_seconds,
                ),
            )

    except SmokeFailure as exc:
        checks.append(CheckResult(name="fatal", ok=False, detail=str(exc)))
        print_summary(checks)
        return 1

    print_summary(checks)
    return 0


def run_check(checks: list[CheckResult], name: str, fn) -> None:
    detail = fn()
    checks.append(CheckResult(name=name, ok=True, detail=str(detail)))


def check_health(client: KilaApiClient) -> str:
    data = client.get("/v1/health")
    if data.get("status") != "ok":
        raise SmokeFailure(f"/v1/health unexpected payload: {data}")
    return "status=ok"


def check_ready(client: KilaApiClient) -> str:
    data = client.get("/v1/ready")
    if data.get("status") != "ready":
        raise SmokeFailure(f"/v1/ready unexpected payload: {data}")
    return "status=ready"


def check_emitter_exists(client: KilaApiClient, emitter_id: str) -> str:
    emitter = client.get(f"/v1/emitters/{emitter_id}")["emitter"]
    return f"emitter_id={emitter['id']} status={emitter['status']}"


def create_smoke_emitter(client: KilaApiClient, args: argparse.Namespace) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    external_id = f"smoke-{suffix}"
    created = client.post(
        "/v1/emitters",
        payload={
            "external_id": external_id,
            "ruc": args.emitter_ruc,
            "dv": args.emitter_dv,
            "legal_name": args.emitter_legal_name,
            "tax_environment": args.emitter_tax_environment,
            "csc": args.emitter_csc,
            "csc_id": args.emitter_csc_id,
        },
        expected_statuses=(201,),
    )
    return created["emitter"]["id"]


def ensure_active_certificate(
    client: KilaApiClient,
    args: argparse.Namespace,
    emitter_id: str,
) -> str:
    certs = client.get(f"/v1/emitters/{emitter_id}/certificates")["certificates"]
    active = [cert for cert in certs if cert["is_active"]]
    if active:
        return f"active_certificate_id={active[0]['id']}"

    if not args.cert_path or not args.cert_password:
        raise SmokeFailure(
            (
                "No active certificate found. Set --cert-path and --cert-password "
                "to let smoke upload+activate one."
            )
        )

    cert_path = Path(args.cert_path)
    if not cert_path.exists():
        raise SmokeFailure(f"Certificate file not found: {cert_path}")

    with cert_path.open("rb") as cert_file:
        uploaded = client.post_multipart(
            f"/v1/emitters/{emitter_id}/certificates",
            data={
                "logical_name": args.cert_logical_name,
                "password": args.cert_password,
            },
            files={
                "file": (
                    cert_path.name,
                    cert_file,
                    "application/x-pkcs12",
                )
            },
            expected_status=201,
        )["certificate"]

    activated = client.post(
        f"/v1/emitters/{emitter_id}/certificates/{uploaded['id']}/activate",
        payload=None,
        expected_statuses=(200,),
    )["certificate"]
    return f"uploaded+activated certificate_id={activated['id']}"


def ensure_active_stamping(
    client: KilaApiClient,
    args: argparse.Namespace,
    emitter_id: str,
) -> str:
    stampings = client.get(f"/v1/emitters/{emitter_id}/stampings")["stampings"]
    active = [stamping for stamping in stampings if stamping["is_active"]]
    if active:
        return f"active_stamping_id={active[0]['id']} number={active[0]['number']}"

    if not args.timbrado_number or not args.timbrado_start_date:
        raise SmokeFailure(
            (
                "No active stamping found. Set --timbrado-number and "
                "--timbrado-start-date to let smoke create+activate one."
            )
        )

    created = client.post(
        f"/v1/emitters/{emitter_id}/stampings",
        payload={
            "number": args.timbrado_number,
            "start_date": args.timbrado_start_date,
            "end_date": None,
        },
        expected_statuses=(201,),
    )["stamping"]

    activated = client.post(
        f"/v1/emitters/{emitter_id}/stampings/{created['id']}/activate",
        payload=None,
        expected_statuses=(200,),
    )["stamping"]
    return (
        f"created+activated stamping_id={activated['id']} number={activated['number']}"
    )


def build_document_payload(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str, str]:
    generated_xml: str
    if args.document_xml_path:
        xml_path = Path(args.document_xml_path)
        if not xml_path.exists():
            raise SmokeFailure(f"Document XML file not found: {xml_path}")
        generated_xml = xml_path.read_text(encoding="utf-8")
    else:
        generated_xml = build_default_unsigned_xml()

    doc_id = extract_doc_id(generated_xml)
    if not doc_id:
        raise SmokeFailure("Could not extract doc_id from generated XML.")

    unique = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    external_id = f"smoke-doc-{unique}"
    idempotency_key = f"smoke-idem-{uuid.uuid4()}"
    payload = {
        "generated_xml": generated_xml,
        "doc_id": doc_id,
        "source": "smoke_kila_api_e2e",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload, external_id, idempotency_key


def build_default_unsigned_xml() -> str:
    helper = load_ares_example_module()
    numero_documento = str(int(time.time()) % 9999999).zfill(7)
    fecha_emision = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    unsigned = helper.build_unsigned_de_base(
        numero_documento=numero_documento,
        fecha_emision=fecha_emision,
        timbrado="80024135",
        fecha_inicio_timbrado="2024-03-11",
        codigo_seguridad="123456789",
        establecimiento="001",
        punto_expedicion="001",
        codigo_actividad="82999",
        descripcion_actividad=(
            "OTRAS ACTIVIDADES DE SERVICIOS DE APOYO A EMPRESAS N.C.P."
        ),
    )
    return unsigned.decode("utf-8")


def load_ares_example_module():
    helper_path = Path(__file__).resolve().parent / "send_ares_factura_test.py"
    spec = importlib.util.spec_from_file_location("send_ares_factura_test", helper_path)
    if spec is None or spec.loader is None:
        raise SmokeFailure("Could not load send_ares_factura_test.py helper module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_doc_id(xml_text: str) -> str | None:
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except etree.XMLSyntaxError:
        return None

    de_node = root.find(f"{{{SIFEN_NS}}}DE")
    if de_node is None:
        return None
    return de_node.get("Id")


def poll_job_until_terminal(
    client: KilaApiClient,
    *,
    job_id: str,
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}")["job"]
        if job["status"] in TERMINAL_JOB_STATUSES:
            return job
        time.sleep(interval_seconds)
    raise SmokeFailure(
        f"Job {job_id} did not reach terminal status within {timeout_seconds}s."
    )


def validate_document_terminal_state(
    *,
    document: dict[str, Any],
    job: dict[str, Any],
    require_approved: bool,
) -> None:
    if require_approved:
        if job["status"] != "succeeded":
            raise SmokeFailure(
                f"Expected succeeded job, got {job['status']} with error={job['error_snapshot']}"
            )
        if document.get("internal_status") != "approved":
            raise SmokeFailure(
                "Expected approved document in strict mode, "
                f"got {document.get('internal_status')}."
            )
        return

    if job["status"] == "succeeded":
        if document.get("internal_status") not in {"approved", "submitted"}:
            raise SmokeFailure(
                "Succeeded job but document status is inconsistent: "
                f"{document.get('internal_status')}"
            )
    elif job["status"] in {"failed", "retry_scheduled"}:
        if not document.get("internal_status"):
            raise SmokeFailure("Terminal non-success job but document status is empty.")
    else:
        raise SmokeFailure(f"Unexpected terminal job status: {job['status']}")


def run_webhook_smoke(
    *,
    client: KilaApiClient,
    emitter_id: str,
    endpoint_id: str,
    timeout_seconds: int,
    interval_seconds: int,
) -> str:
    sent = client.post(
        f"/v1/emitters/{emitter_id}/webhooks/{endpoint_id}/test",
        expected_statuses=(201,),
    )
    delivery = sent["delivery"]
    job = sent["job"]
    final_job = poll_job_until_terminal(
        client,
        job_id=job["id"],
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
    )
    delivery_state = client.get(
        f"/v1/emitters/{emitter_id}/webhook-deliveries/{delivery['id']}"
    )["delivery"]
    if delivery_state["final_status"] not in TERMINAL_DELIVERY_STATUSES:
        raise SmokeFailure(
            f"Webhook delivery not terminal: {delivery_state['final_status']}"
        )
    return (
        f"delivery_id={delivery['id']} job_status={final_job['status']} "
        f"delivery_status={delivery_state['final_status']}"
    )


def print_summary(checks: list[CheckResult]) -> None:
    print("\n=== Kila API E2E Smoke Summary ===")
    for result in checks:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    failed = [result for result in checks if not result.ok]
    if failed:
        print("\nOVERALL: FAIL")
    else:
        print("\nOVERALL: PASS")


if __name__ == "__main__":
    raise SystemExit(main())
