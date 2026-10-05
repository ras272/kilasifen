import json

from scripts.export_openapi import (
    DEFAULT_OUTPUT,
    SUMMARY_TRANSLATIONS,
    TAG_METADATA,
    build_openapi_schema,
)


def test_documentation_openapi_summaries_and_tags_are_in_spanish() -> None:
    exported = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    untranslated = sorted(
        operation["summary"]
        for path_item in exported["paths"].values()
        for operation in path_item.values()
        if operation["summary"] not in SUMMARY_TRANSLATIONS.values()
    )
    assert untranslated == []
    assert {tag["name"] for tag in exported["tags"]} <= set(TAG_METADATA)


def test_documentation_openapi_export_matches_application_contract() -> None:
    exported = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert exported == build_openapi_schema()
    api_key_scheme = exported["components"]["securitySchemes"]["KilaApiKey"]
    assert api_key_scheme == {
        "type": "apiKey",
        "description": (
            "Credencial privada del consumidor. Nunca la expongas en un navegador "
            "ni en una app cliente."
        ),
        "in": "header",
        "name": "X-API-Key",
    }
    assert "/v1/emitters/{emitter_id}/documents/facturas" in exported["paths"]
    assert "/v1/emitters/{emitter_id}/documents/notas-credito" in exported["paths"]
    assert "/v1/emitters/{emitter_id}/documents/notas-debito" in exported["paths"]
