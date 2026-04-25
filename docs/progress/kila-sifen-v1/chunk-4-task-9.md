# Chunk 4 - Task 9

## Goal

Add queue wiring and worker entrypoints on top of the new document/job lifecycle.

## Commit

- `7232dee` `feat: add background queue and worker wiring`

## What was created

- `RQ` queue adapter
- worker entrypoint for document jobs
- job-service helper to hydrate document job context
- queue tests with `fakeredis`

## Behavior introduced

- document jobs can be enqueued through the platform queue adapter
- worker entrypoints can load persisted job/document state from DB
- the worker layer stays thin and delegates context loading to application services

## Main files

- `kilasifen/application/jobs/service.py`
- `kilasifen/infrastructure/jobs/queue.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `tests/infrastructure/test_rq_queue.py`

## Verification

- `pytest tests/infrastructure/test_rq_queue.py tests/api/test_jobs_api.py tests/api/test_documents_api.py tests/application/test_document_idempotency.py -v`
- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_emitters_api.py tests/api/test_certificates_api.py tests/api/test_stampings_api.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/application/test_certificate_activation.py tests/application/test_document_idempotency.py tests/infrastructure/test_db_foundation.py tests/infrastructure/test_certificate_store.py tests/infrastructure/test_rq_queue.py -v`
- result at close time: `22 passed`

## Notes

- current `RQ` test run still emits a deprecation warning from `rq` internals using `datetime.utcnow()`
- the warning is upstream behavior, not from Kila SIFEN code
