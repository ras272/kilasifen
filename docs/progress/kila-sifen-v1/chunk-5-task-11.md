# Chunk 5 - Task 11

## Goal

Add read-side SIFEN query workflows for RUC lookup and document status lookup.

## Commit

- `7373379` `feat: add query workflows`

## What was created

- query service layer under `router -> service -> repository`
- new query router with emitter-scoped endpoints
- normalized API contracts for:
  - query RUC
  - query document
- `pysifen`-backed query adapter using `ConsultaSIFEN`
- persistence of last document-query traces:
  - `last_query_request_xml`
  - `last_query_response_raw`
  - `last_query_at`

## Endpoints added

- `GET /v1/emitters/{emitter_id}/queries/ruc/{ruc}`
- `GET /v1/emitters/{emitter_id}/queries/documents/{document_id}`

## Main files

- `kilasifen/application/queries/service.py`
- `kilasifen/api/routers/queries.py`
- `kilasifen/api/schemas/queries.py`
- `kilasifen/infrastructure/sifen/query.py`
- `kilasifen/infrastructure/db/repositories/documents.py`
- `tests/api/test_queries_api.py`

## Verification

- `pytest tests/api/test_queries_api.py -v`
- `pytest tests/api/test_queries_api.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/application/test_emission_flow.py tests/infrastructure/test_rq_queue.py -v`
- result at close time: `11 passed`

## Notes

- `ruff` was not available in this environment as command or Python module, so lint verification could not be run here
- queue tests still show the same upstream `rq` deprecation warning around `datetime.utcnow()`
