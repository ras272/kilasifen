# Chunk 13 - Task 28

## What this task is

Refactor the remaining global resource routes into emitter-scoped ones
and lock their service lookups to the emitter in the path.

## Commit

- commit message:
  `test/audit: add cross-emitter isolation coverage and emitter-scoped routes`

## What changed

- Moved these routes to emitter-scoped paths:
  - `GET /v1/documents/{id}` -> `GET /v1/emitters/{emitter_id}/documents/{id}`
  - `GET /v1/jobs/{id}` -> `GET /v1/emitters/{emitter_id}/jobs/{id}`
  - `GET /v1/events/{id}` -> `GET /v1/emitters/{emitter_id}/events/{id}`
  - `POST /v1/certificates/{id}/activate`
    -> `POST /v1/emitters/{emitter_id}/certificates/{id}/activate`
  - `POST /v1/stampings/{id}/activate`
    -> `POST /v1/emitters/{emitter_id}/stampings/{id}/activate`
  - `POST /v1/webhooks/{id}/deliveries/replay`
    -> `POST /v1/emitters/{emitter_id}/webhooks/{id}/deliveries/replay`
  - `GET /v1/webhook-deliveries/{id}`
    -> `GET /v1/emitters/{emitter_id}/webhook-deliveries/{id}`
- Added service methods that enforce ownership without breaking the
  admin/operator flows that still use non-scoped internals.
- Added tests for:
  - success on the new scoped routes
  - cross-emitter access returning `404`
  - invalid API key returning `401`

## Verification

- `python -m pytest tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_events_api.py tests/api/test_certificates_api.py tests/api/test_stampings_api.py tests/api/test_webhooks_api.py tests/api/test_admin_console.py -q`
  - result: `57 passed`
- `python -m pytest -q`
  - result: `340 passed, 5 skipped`

## Notes

- This task intentionally does **not** add rate limiting, Postgres RLS,
  or a production Docker image flow. Those remain out of scope for this
  chunk and for `PASO 6A`.
