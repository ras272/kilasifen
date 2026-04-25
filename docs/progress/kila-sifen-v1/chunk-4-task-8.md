# Chunk 4 - Task 8

## Goal

Model documents and jobs with idempotent creation, without yet calling real SIFEN.

## Commit

- `5accd84` `feat: add document and job lifecycle foundation`

## What was created

- document domain model
- job domain model
- document repository interface and SQLAlchemy implementation
- job repository interface and SQLAlchemy implementation
- document service layer
- job service layer
- document schemas
- job schemas
- document router
- job router

## Behavior introduced

- creating a document also creates a queued job
- repeated creation with the same `idempotency_key` for the same emitter returns the same document and the same job
- first create returns `201`
- idempotent replay returns `200`
- job detail is readable through the API

## Endpoints added

- `POST /v1/emitters/{emitter_id}/documents`
- `GET /v1/documents/{document_id}`
- `GET /v1/jobs/{job_id}`

## Verification

- `pytest tests/application/test_document_idempotency.py tests/api/test_documents_api.py tests/api/test_jobs_api.py -v`
- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_emitters_api.py tests/api/test_certificates_api.py tests/api/test_stampings_api.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/application/test_certificate_activation.py tests/application/test_document_idempotency.py tests/infrastructure/test_db_foundation.py tests/infrastructure/test_certificate_store.py -v`
- result at close time: `20 passed`
