# Chunk 8 - Task 23

## Goal

Close the XML retrieval isolation gap by enforcing emitter ownership in the API
route and service flow.

## Commit

- `167cd6e` `fix: scope document xml endpoint by emitter`

## What was changed

- Moved XML retrieval route to emitter-scoped path:
  - `GET /v1/emitters/{emitter_id}/documents/{document_id}/xml`
- Updated document service XML lookup to enforce emitter ownership:
  - `get_document_xml_for_emitter(emitter_id, document_id)`
  - cross-emitter access returns `404` via existing not-found semantics.
- Added explicit test for cross-emitter isolation on XML download.
- Added TODO markers and coverage tests documenting current system-wide
  operator behavior for:
  - `GET /v1/jobs` without `emitter_id`
  - `GET /v1/webhook-deliveries` without `emitter_id`

## Validation

- `pytest tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_webhooks_api.py`
- result at close time: `18 passed`
- `python -m ruff check kilasifen/application/documents/service.py kilasifen/api/routers/documents.py kilasifen/api/routers/jobs.py kilasifen/api/routers/webhooks.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_webhooks_api.py --select F`
- result at close time: `ruff: All checks passed`
