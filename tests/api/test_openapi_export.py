import json

from scripts.export_openapi import DEFAULT_OUTPUT, build_openapi_schema


def test_documentation_openapi_export_matches_application_contract() -> None:
    exported = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert exported == build_openapi_schema()
    api_key_scheme = exported["components"]["securitySchemes"]["KilaApiKey"]
    assert api_key_scheme == {
        "type": "apiKey",
        "description": (
            "Private consumer credential. Never expose it to browser clients."
        ),
        "in": "header",
        "name": "X-API-Key",
    }
    assert "/v1/emitters/{emitter_id}/documents/facturas" in exported["paths"]
    assert "/v1/emitters/{emitter_id}/documents/notas-credito" in exported["paths"]
