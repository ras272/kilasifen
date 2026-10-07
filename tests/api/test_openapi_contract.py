import pytest
from cryptography.fernet import Fernet

from kilasifen.api.app import create_app
from kilasifen.config import get_settings


def test_openapi_describes_consumer_security_and_supported_contracts(
    monkeypatch,
) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    schema = create_app().openapi()

    assert schema["info"]["version"] == "v1"
    assert schema["components"]["securitySchemes"]["KilaApiKey"] == {
        "type": "apiKey",
        "description": (
            "Credencial privada del consumidor. Nunca la expongas en un navegador "
            "ni en una app cliente."
        ),
        "in": "header",
        "name": "X-API-Key",
    }

    required_paths = {
        "/v1/emitters/{emitter_id}/documents/facturas",
        "/v1/emitters/{emitter_id}/documents/notas-credito",
        "/v1/emitters/{emitter_id}/documents/notas-debito",
        "/v1/emitters/{emitter_id}/documents/{document_id}",
        "/v1/emitters/{emitter_id}/jobs/{job_id}",
        "/v1/emitters/{emitter_id}/documents/{document_id}/xml",
        "/v1/emitters/{emitter_id}/documents/{document_id}/kude",
        "/v1/emitters/{emitter_id}/documents/{document_id}/kude/data",
        "/v1/emitters/{emitter_id}/documents/{document_id}/cancel",
        "/v1/emitters/{emitter_id}/inutilizations",
        "/v1/emitters/{emitter_id}/webhooks",
    }
    assert required_paths <= set(schema["paths"])

    factura = schema["paths"]["/v1/emitters/{emitter_id}/documents/facturas"]["post"]
    assert factura["security"] == [{"KilaApiKey": []}]
    assert {"200", "201", "422"} <= set(factura["responses"])

    raw_document = schema["paths"]["/v1/emitters/{emitter_id}/documents"]["post"]
    raw_event = schema["paths"]["/v1/emitters/{emitter_id}/events"]["post"]
    assert raw_document["deprecated"] is True
    assert raw_event["deprecated"] is True

    typed_payload = schema["components"]["schemas"]["FacturaContractPayload"]
    assert typed_payload["additionalProperties"] is False
    assert "generated_xml" not in typed_payload["properties"]
    assert "signed_xml" not in typed_payload["properties"]

    get_settings.cache_clear()


def test_openapi_declares_the_error_envelope_for_client_errors(monkeypatch) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    schema = create_app().openapi()
    envelope_ref = {"$ref": "#/components/schemas/ErrorEnvelope"}

    def error_schemas(path: str, method: str) -> dict[str, dict]:
        responses = schema["paths"][path][method]["responses"]
        return {
            status: response["content"]["application/json"]["schema"]
            for status, response in responses.items()
            if status.startswith(("4", "5"))
        }

    factura = error_schemas("/v1/emitters/{emitter_id}/documents/facturas", "post")
    assert set(factura) == {
        "401",
        "403",
        "404",
        "409",
        "413",
        "422",
        "429",
        "503",
    }
    assert all(item == envelope_ref for item in factura.values())

    job = error_schemas("/v1/emitters/{emitter_id}/jobs/{job_id}", "get")
    assert set(job) == {"401", "403", "404", "422", "429", "503"}

    auth_check = error_schemas("/v1/auth/check", "get")
    assert set(auth_check) == {"401", "429", "503"}

    for path, method in (
        ("/v1/emitters/{emitter_id}/documents/facturas", "post"),
        ("/v1/auth/check", "get"),
    ):
        rate_limited = schema["paths"][path][method]["responses"]["429"]
        assert set(rate_limited["headers"]) == {"Retry-After", "X-Correlation-ID"}

    upload = error_schemas("/v1/emitters/{emitter_id}/certificates", "post")
    assert "415" in upload

    assert {"ErrorEnvelope", "ErrorPayload"} <= set(schema["components"]["schemas"])
    assert "HTTPValidationError" not in schema["components"]["schemas"]

    get_settings.cache_clear()


def test_openapi_declares_the_correlation_header_on_every_response(
    monkeypatch,
) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    schema = create_app().openapi()

    missing = [
        f"{method.upper()} {path} {status}"
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        for status, response in operation["responses"].items()
        if "X-Correlation-ID" not in response.get("headers", {})
    ]
    assert missing == []

    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("path", "method", "scope"),
    [
        ("/v1/emitters/{emitter_id}", "get", "`tenant:read`"),
        ("/v1/emitters/{emitter_id}", "patch", "`tenant:write`"),
        ("/v1/emitters/{emitter_id}/documents/facturas", "post", "`fiscal:write`"),
        ("/v1/emitters/{emitter_id}/events/{event_id}", "get", "`fiscal:write`"),
        ("/v1/emitters/{emitter_id}/certificates", "get", "`secrets:write`"),
        ("/v1/emitters/{emitter_id}/webhooks", "post", "`tenant:write`"),
        ("/v1/jobs", "get", "`platform:admin`"),
        ("/v1/emitters", "post", "`emitters:create`"),
        ("/v1/emitters", "get", "`tenant:read`"),
        ("/v1/emitters/{emitter_id}/jobs/{job_id}/retry", "post", "`fiscal:write`"),
    ],
)
def test_openapi_documents_the_scope_each_operation_enforces(
    monkeypatch, path: str, method: str, scope: str
) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    operation = create_app().openapi()["paths"][path][method]

    assert f"**Scope:** {scope}" in operation["description"]

    get_settings.cache_clear()


def test_openapi_scope_note_covers_every_authenticated_operation(monkeypatch) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    schema = create_app().openapi()

    undocumented = [
        f"{method.upper()} {path}"
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if operation.get("security") and "**Scope:**" not in operation["description"]
    ]
    assert undocumented == []

    get_settings.cache_clear()


def test_openapi_types_the_data_of_every_json_success_response(monkeypatch) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    schema = create_app().openapi()
    components = schema["components"]["schemas"]

    untyped = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            for status, response in operation["responses"].items():
                content = response.get("content", {})
                if not status.startswith("2") or "application/json" not in content:
                    continue
                ref = content["application/json"]["schema"].get("$ref", "")
                envelope = components.get(ref.rsplit("/", 1)[-1], {})
                data = envelope.get("properties", {}).get("data", {})
                required = set(envelope.get("required", []))
                if required != {"data", "correlation_id"} or "$ref" not in data:
                    untyped.append(f"{method.upper()} {path} {status}")
    assert untyped == []

    created = schema["paths"]["/v1/emitters/{emitter_id}/documents/facturas"]["post"]
    for status in ("200", "201"):
        ref = created["responses"][status]["content"]["application/json"]["schema"]
        assert ref == {"$ref": "#/components/schemas/CreatedDocumentEnvelope"}
    assert set(components["CreatedDocumentData"]["required"]) == {"document", "job"}
    assert "fiscal_warnings" in components["DocumentResponse"]["properties"]

    get_settings.cache_clear()


def test_openapi_declares_the_media_type_of_downloads(monkeypatch) -> None:
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    paths = create_app().openapi()["paths"]
    prefix = "/v1/emitters/{emitter_id}/documents/{document_id}"

    xml = paths[f"{prefix}/xml"]["get"]["responses"]["200"]["content"]
    kude = paths[f"{prefix}/kude"]["get"]["responses"]["200"]["content"]

    assert xml == {"application/xml": {"schema": {"type": "string"}}}
    assert kude == {
        "application/pdf": {"schema": {"type": "string", "format": "binary"}}
    }

    get_settings.cache_clear()
