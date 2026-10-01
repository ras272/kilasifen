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
            "Private consumer credential. Never expose it to browser clients."
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
    assert set(factura) == {"401", "403", "404", "409", "422", "429", "503"}
    assert all(item == envelope_ref for item in factura.values())

    job = error_schemas("/v1/emitters/{emitter_id}/jobs/{job_id}", "get")
    assert set(job) == {"401", "403", "404", "422", "429", "503"}

    auth_check = error_schemas("/v1/auth/check", "get")
    assert set(auth_check) == {"401", "429", "503"}

    assert {"ErrorEnvelope", "ErrorPayload"} <= set(schema["components"]["schemas"])
    assert "HTTPValidationError" not in schema["components"]["schemas"]

    get_settings.cache_clear()
