# Chunk 7 - Task 18

## Goal

Ensure document emission jobs are enqueued automatically and runnable on Windows workers.

## Commit

- `b5fd977` `feat: auto-enqueue document jobs and add windows-safe rq worker`

## What was changed

- `DocumentService` now supports optional queue wiring for `document.emit` enqueue on document creation.
- API dependency wiring enables auto-enqueue when `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE=true`.
- new cross-platform worker class:
  - `kilasifen.infrastructure.jobs.worker_classes.CrossPlatformSimpleWorker`
  - uses `TimerDeathPenalty` to avoid Unix-only signal errors on Windows.
- tests added:
  - document service enqueue behavior
  - worker class timeout strategy

## Validation

- `pytest tests/application/test_document_idempotency.py tests/infrastructure/test_worker_classes.py tests/api/test_documents_api.py tests/api/test_jobs_api.py -v`
- `python -m ruff check <changed files> --select F`
- operational smoke run with local API + fake Redis + worker:
  - `python docs/examples/smoke_kila_api_e2e.py --job-timeout-seconds 180 --poll-interval-seconds 2`
  - result: `OVERALL: PASS`

## Notes

- Windows worker should be started with:
  - `--worker-class kilasifen.infrastructure.jobs.worker_classes.CrossPlatformSimpleWorker`

