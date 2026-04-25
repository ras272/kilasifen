# Job Lifecycle

## Why this exists

Kila SIFEN is async-first for emission and outgoing integrations.
Jobs are the operational ledger for retries, observability, and support.

## Core statuses

- `queued`: created and waiting execution
- `retry_scheduled`: transient failure, can be retried
- `succeeded`: completed successfully
- `failed`: terminal failure or non-retryable rejection

## Document emission flow

1. API creates `document` + `job` (`document.emit`).
2. Worker hydrates context:
   - emitter
   - active certificate
   - active stamping
3. Worker calls SIFEN engine and persists traces.
4. Outcomes:
   - approved/accepted => `job.succeeded`
   - transport timeout/network => `job.retry_scheduled`
   - fiscal validation/rejection => `job.failed`

## Webhook delivery flow

1. Endpoint replay/event creates `webhook_delivery` + `job` (`webhook.deliver`).
2. Worker signs payload and performs HTTP POST.
3. Outcomes:
   - `2xx` => `delivery.delivered`, `job.succeeded`
   - `5xx` or transport error => `delivery.retry_pending`, `job.retry_scheduled`
   - `4xx` => `delivery.failed`, `job.failed`

## Manual operator actions

Admin console allows:

- retrying failed/scheduled jobs for:
  - `document.emit`
  - `webhook.deliver`
- activating a replacement certificate

Retries re-queue job payload with current DB/crypto settings.

## Recommended monitoring

- ratio of `failed` + `retry_scheduled` by job type
- aging of jobs in `queued`
- webhook failure concentration per endpoint
- document rejection codes from SIFEN

## References

- `docs/normativa/sifen-async-notas-tecnicas.md`
- `kilasifen/domain/common/sifen_async.py`

