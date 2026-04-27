# Chunk 15 - Task 30

## What this task is

Add optional Sentry integration for production monitoring without
leaking XML payloads, encrypted certificate data, CSC values, or noisy
trace volume.

## Commit

- commit message:
  `feat: optional Sentry integration with sensitive data scrubbing`

## What changed

- Added new settings:
  - `KILA_SIFEN_SENTRY_DSN`
  - `KILA_SIFEN_SENTRY_ENVIRONMENT`
  - `KILA_SIFEN_SENTRY_RELEASE`
  - `KILA_SIFEN_SENTRY_TRACES_SAMPLE_RATE` (default `0.0`)
- Added `kilasifen/observability.py` with:
  - optional SDK loading
  - API/worker bootstrap helpers
  - `before_send`, `before_breadcrumb`, and
    `before_send_transaction` scrubbing hooks
- Explicitly redacts these fields anywhere they appear in event
  payloads:
  - `generated_xml`
  - `signed_xml`
  - `sifen_request_xml`
  - `sifen_response_raw`
  - `last_query_request_xml`
  - `last_query_response_raw`
  - `payload_snapshot`
  - `encrypted_p12`
  - `encrypted_password`
  - `csc`
  - `csc_id`
- Added defensive exception-value redaction for:
  - `BEGIN CERTIFICATE`
  - `BEGIN PRIVATE KEY`
  - base64-like blobs longer than 200 chars
- API startup now initializes Sentry through `create_app()`.
- Worker entrypoints now initialize Sentry independently through
  `ensure_worker_observability()`.
- Added tests covering:
  - event scrubbing
  - breadcrumb scrubbing
  - API init wiring
  - worker init wiring
  - SDK config defaults

## Verification

- `python -m pytest tests/test_observability.py tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py -q`
  - result: `16 passed`
- `python -m pytest -q`
  - result: `351 passed, 5 skipped`
- `ruff check kilasifen/observability.py kilasifen/config.py kilasifen/api/app.py kilasifen/infrastructure/jobs/workers.py pyproject.toml tests/test_observability.py tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py`
  - result: `All checks passed!`

## Notes

- `LoggingIntegration` is configured as `level=INFO,
  event_level=ERROR`, so `INFO` logs stay as breadcrumbs and only
  `ERROR` logs become Sentry events.
- Out of scope and intentionally not implemented here:
  - rate limiting
  - Postgres RLS
  - production container/image flow
