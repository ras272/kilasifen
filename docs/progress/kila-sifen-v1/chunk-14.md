# Chunk 14

## Purpose

Add production-grade request and worker observability without changing
the fiscal behavior of the API.

## Why it exists

After route scoping was tightened in Chunk 13, the next operational need
was traceability: when a request enqueues RQ work, we need one
correlation id across HTTP logs, queue metadata, and worker execution.

This chunk adds that foundation before Sentry.

## Closed tasks

- `Task Logging-Correlation` commit message
  `feat: structured JSON logging with correlation_id propagation`
  - emit JSON logs, bind correlation ids with `contextvars`, propagate
    them through RQ job metadata, and persist the worker-side
    correlation id on jobs for later debugging.

## Main files

- `kilasifen/logging.py`
- `kilasifen/api/app.py`
- `kilasifen/infrastructure/jobs/queue.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `tests/test_logging.py`
- `tests/api/test_health.py`
- `tests/infrastructure/test_rq_queue.py`
- `tests/application/test_emission_flow.py`
- `tests/application/test_webhook_delivery.py`

## Decisions taken

- Logging stays on the stdlib stack; no `structlog` or extra logging
  framework was introduced.
- The API generates one correlation id per request, returns it in
  `X-Correlation-ID`, and logs `http.request.completed` with structured
  fields.
- RQ jobs inherit the correlation id through `job.meta`, and workers
  re-bind it into the execution context before emitting logs or updating
  job state.
