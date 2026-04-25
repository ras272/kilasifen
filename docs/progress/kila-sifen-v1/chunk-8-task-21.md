# Chunk 8 - Task 21

## Goal

Implement typed JSON to unsigned XML generation for `factura` and `nota_credito`
so ERP integrations can emit typed documents without sending XML manually.

## Commit

- `11b8f2e` `feat: build factura and nota credito xml from typed contracts`

## What was changed

- Added typed XML builder module:
  - `kilasifen/infrastructure/sifen/typed_xml_builder.py`
- `PysifenPayloadMapper` now resolves typed contracts when `generated_xml` or
  `signed_xml` is not provided:
  - `factura_v1`
  - `nota_credito_v1`
- XML generation includes:
  - CDC generation from emitter + stamping + typed payload
  - core DE groups (`gOpeDE`, `gTimb`, `gDatGralOpe`, items, totals)
  - nota crédito associated document (`gCamDEAsoc`)
- Typed API schema validation now allows XML-less payloads for supported typed
  contracts when required business fields are present.
- Typed example updated to show XML-less request payload:
  - `docs/examples/kila_api_emit_factura_typed.py`

## Validation

- `pytest tests/infrastructure/test_typed_xml_builder.py tests/api/test_documents_api.py tests/application/test_emission_flow.py -v`
- `python -m ruff check kilasifen/infrastructure/sifen/typed_xml_builder.py kilasifen/infrastructure/sifen/mapper.py kilasifen/infrastructure/sifen/engine.py kilasifen/api/schemas/documents.py tests/infrastructure/test_typed_xml_builder.py tests/api/test_documents_api.py docs/examples/kila_api_emit_factura_typed.py --select F`
- result at close time: `15 passed`, `ruff: All checks passed`

## Notes

- This is an incremental builder focused on high-value typed paths.
- `recibo` remains typed-contract-ready but still requires XML transport payload
  until its dedicated builder is implemented.
