# Chunk 8 - Task 20

## Goal

Expose typed document endpoints for ERP integrations while keeping the raw
document endpoint for advanced compatibility.

## Commit

- `2b02e16` `feat: add typed document contracts for factura nota credito and recibo`

## What was changed

- Added typed API contracts:
  - `FacturaCreateRequest`
  - `NotaCreditoCreateRequest`
  - `ReciboCreateRequest` (removed later because recibo is not a SIFEN DE type)
- Added strict transport validation:
  - requires `generated_xml` or `signed_xml` in typed payloads.
- Added new endpoints:
  - `POST /v1/emitters/{emitter_id}/documents/facturas`
  - `POST /v1/emitters/{emitter_id}/documents/notas-credito`
  - `POST /v1/emitters/{emitter_id}/documents/recibos` (removed later)
- Preserved existing raw endpoint:
  - `POST /v1/emitters/{emitter_id}/documents`
- Typed endpoints store normalized contract metadata in payload snapshot for
  forward-compatible JSON builder evolution.
- Added typed usage example:
  - `docs/examples/kila_api_emit_factura_typed.py`

## Validation

- `pytest tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_webhooks_api.py -v`
- `python -m ruff check kilasifen/api/routers/documents.py kilasifen/api/schemas/documents.py tests/api/test_documents_api.py --select F`
- result at close time: `9 passed`, `ruff: All checks passed`

## Notes

- This is an incremental hybrid step: contracts are typed now, while deep JSON
  to XML construction will be expanded in next tasks.
