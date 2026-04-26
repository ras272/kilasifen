# Chunk 13

## Purpose

Start `PASO 6` of the MVP with the highest-risk production concern:
strict multi-emitter isolation on resource-detail endpoints.

## Why it exists

At this stage the API already emits documents, events and KuDE, but a
few resource routes still used global identifiers (`document_id`,
`job_id`, `event_id`, `certificate_id`, `stamping_id`, `endpoint_id`,
`delivery_id`) without an emitter-scoped path.

That is acceptable for a single operator during development, but not
for a multi-emitter ERP. This chunk closes that gap before adding
logging or Sentry.

## Closed tasks

- `Task Audit-Routes` commit message
  `test/audit: add cross-emitter isolation coverage and emitter-scoped routes`
  - move resource-detail endpoints to emitter-scoped routes, enforce
    service-level ownership checks, and add auth/isolation tests.

## Main files

- `kilasifen/api/routers/documents.py`
- `kilasifen/api/routers/jobs.py`
- `kilasifen/api/routers/events.py`
- `kilasifen/api/routers/certificates.py`
- `kilasifen/api/routers/stampings.py`
- `kilasifen/api/routers/webhooks.py`
- `kilasifen/application/jobs/service.py`
- `kilasifen/application/events/service.py`
- `kilasifen/application/certificates/service.py`
- `kilasifen/application/stampings/service.py`
- `kilasifen/application/webhooks/service.py`
- `tests/api/test_documents_api.py`
- `tests/api/test_jobs_api.py`
- `tests/api/test_events_api.py`
- `tests/api/test_certificates_api.py`
- `tests/api/test_stampings_api.py`
- `tests/api/test_webhooks_api.py`
- `tests/api/test_admin_console.py`

## Decisions taken

- Resource detail routes now require `emitter_id` in the path and return
  `404` on emitter mismatch to avoid existence leaks.
- Authentication still runs first through the shared `X-API-Key`
  dependency, so invalid API keys return `401` before ownership checks.
- System-wide list routes (`GET /v1/jobs`, `GET /v1/webhook-deliveries`)
  stay unchanged for now, with existing TODOs preserved, because they
  are operator-facing and explicitly out of this commit's scope.
