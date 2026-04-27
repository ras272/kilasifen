# Chunk 14 - Task 29

## What this task is

Introduce structured JSON logging and carry the same correlation id from
the originating HTTP request into queued document and webhook workers.

## Commit

- commit message:
  `feat: structured JSON logging with correlation_id propagation`

## What changed

- Replaced the old plain logging setup with a JSON formatter in
  `kilasifen/logging.py`.
- Added context-bound helpers:
  - `set_correlation_id(...)`
  - `reset_correlation_id(...)`
  - `get_correlation_id(...)`
- Updated the FastAPI app middleware to:
  - generate one correlation id per request
  - expose it as `X-Correlation-ID`
  - emit `http.request.completed` with method, path, route,
    status code, duration, and emitter id
- Updated `RqJobQueue` to copy the active correlation id into
  `job.meta`.
- Updated document and webhook workers to:
  - restore the correlation id from `rq.get_current_job().meta`
  - log start/finish events with structured fields
  - persist `worker_correlation_id` on the job snapshot
- Added tests for:
  - JSON formatter output
  - request logging
  - queue metadata propagation
  - worker propagation for document jobs
  - worker propagation for webhook jobs

## Verification

- `python -m pytest tests/api/test_health.py tests/test_logging.py tests/infrastructure/test_rq_queue.py tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py -q`
  - result: `17 passed, 4 warnings`
- `python -m pytest -q`
  - result: `345 passed, 5 skipped`
- `ruff check kilasifen/logging.py kilasifen/api/app.py kilasifen/infrastructure/jobs/queue.py kilasifen/infrastructure/jobs/workers.py tests/api/test_health.py tests/test_logging.py tests/infrastructure/test_rq_queue.py tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py`
  - result: `All checks passed!`

## Notes

- This task intentionally does **not** add Sentry yet; it only prepares
  the logging/correlation substrate needed before that integration.
- Rate limiting, Postgres RLS, and production containerization remain
  out of scope for this task and for this stage of `PASO 6`.
