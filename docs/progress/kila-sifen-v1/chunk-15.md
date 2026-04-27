# Chunk 15

## Purpose

Finish `PASO 6` with production error reporting that is safe to enable
for real tenants.

## Why it exists

Once route scoping and correlation-aware logging were in place, the last
missing operational piece was exception monitoring. This chunk adds
optional Sentry initialization for both API and workers, but only with
explicit redaction of fiscal payloads, secrets, and certificate-like
blobs.

## Closed tasks

- `Task Sentry-Optional` commit message
  `feat: optional Sentry integration with sensitive data scrubbing`
  - add env-gated Sentry init, worker/API bootstrap hooks, and
    scrubbing for XML payloads, encrypted secrets, CSC values, and
    certificate-like exception bodies.

## Main files

- `kilasifen/observability.py`
- `kilasifen/config.py`
- `kilasifen/api/app.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `pyproject.toml`
- `tests/test_observability.py`
- `tests/application/test_emission_flow.py`
- `tests/application/test_webhook_delivery.py`

## Decisions taken

- Sentry stays fully optional; without `KILA_SIFEN_SENTRY_DSN`, startup
  behavior is unchanged.
- API and worker initialization are separate because RQ runs in a
  different process.
- Default tracing sample rate is `0.0`, and only `ERROR` logs are sent
  as Sentry events while `INFO` logs remain breadcrumbs.
- The scrubbing layer redacts known payload fields plus certificate and
  base64-like blobs found inside exception values.
