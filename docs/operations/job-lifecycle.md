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
5. Optional webhook fanout:
   - if `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS=true`, document transitions publish
     events like `document.approved`, `document.rejected`, `document.retry_pending`
     to active subscribed webhook endpoints.

If transport becomes uncertain after XML generation, the exact generated/signed
payload and CDC remain durable. A retry queries SIFEN by CDC first; an existing
DTE converges to approved without resubmission. The same payload is submitted
again only after a not-found result. Automatic attempts are bounded to five.

## Fiscal event flow

1. API validates/signs cancelation or inutilization and creates `event` +
   `event.submit` job.
2. The `events` worker loads emitter/certificate secrets from the database; no
   secret is stored in the Redis job payload.
3. Approved cancelation moves the document to `cancelled`; approved
   inutilization stores its SIFEN protocol and publishes the terminal webhook.
4. Transport failures become `retry_pending`/`retry_scheduled` and use a bounded
   five-attempt schedule. Validation/rejection is terminal.

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
  - `event.submit`
  - `webhook.deliver`
- activating a replacement certificate

Retries re-queue job payload with current DB/crypto settings.

## Recommended monitoring

- ratio of `failed` + `retry_scheduled` by job type
- aging of jobs in `queued`
- missing workers for any of `documents`, `events`, `webhooks`
- webhook failure concentration per endpoint
- document rejection codes from SIFEN

## References

- `docs/normativa/sifen-async-notas-tecnicas.md`
- `kilasifen/domain/common/sifen_async.py`
