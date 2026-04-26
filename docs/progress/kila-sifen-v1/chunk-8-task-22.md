# Chunk 8 - Task 22

## Goal

Improve operational API ergonomics with list/filter endpoints, emitter health
snapshot, XML retrieval endpoint, and emitter-scoped isolation checks.

## Commit

- `10e7c1a` `feat: add operational list filters emitter health and xml retrieval`

## What was changed

- Added operational list endpoints with pagination and filters:
  - `GET /v1/emitters/{emitter_id}/documents`
  - `GET /v1/jobs`
  - `GET /v1/webhook-deliveries`
- Added document XML retrieval endpoint:
  - `GET /v1/documents/{document_id}/xml` (superseded in Task 23)
  - returns signed XML when available, otherwise generated XML from persisted payload.
- Added emitter operational health endpoint:
  - `GET /v1/emitters/{emitter_id}/health`
  - includes certificate/stamping availability, queue snapshot, and last document status.
- Extended repository/service filtering capabilities with pagination offsets:
  - documents, jobs, webhook deliveries.
- Added emitter-scoped isolation tests for document/job/webhook list flows.

## Validation

- `pytest tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_webhooks_api.py tests/api/test_emitters_api.py tests/api/test_admin_console.py -v`
- `python -m ruff check kilasifen/application/emitters/health.py kilasifen/application/documents/service.py kilasifen/application/jobs/service.py kilasifen/application/webhooks/service.py kilasifen/api/deps.py kilasifen/api/routers/documents.py kilasifen/api/routers/jobs.py kilasifen/api/routers/webhooks.py kilasifen/api/routers/emitters.py kilasifen/api/schemas/emitters.py kilasifen/repositories/documents.py kilasifen/repositories/jobs.py kilasifen/repositories/webhooks.py kilasifen/infrastructure/db/repositories/documents.py kilasifen/infrastructure/db/repositories/jobs.py kilasifen/infrastructure/db/repositories/webhooks.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_webhooks_api.py tests/api/test_emitters_api.py --select F`
- result at close time: `21 passed`, `ruff: All checks passed`

## Notes

- This task introduces operational read-side visibility requested for P0 support
  workflows while keeping existing write APIs backward compatible.
