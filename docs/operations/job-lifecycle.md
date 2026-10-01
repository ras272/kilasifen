# Job Lifecycle

## Why this exists

Kila SIFEN is async-first for emission and outgoing integrations.
Jobs are the operational ledger for retries, observability, and support.

## Core statuses

- `queued`: created and waiting execution
- `processing`: an attempt is running (committed before the SIFEN call; a
  job that stays here after its worker died needs an operator retry)
- `retry_scheduled`: transient failure, can be retried
- `succeeded`: completed successfully
- `failed`: terminal failure or non-retryable rejection

## Document emission flow

1. API creates `document` + `job` (`document.emit`).
2. Worker hydrates context:
   - emitter
   - active certificate
   - active stamping
3. Each attempt uses two short transactions and holds no transaction or
   row lock while SIFEN answers:
   - transaction 1 locks emitter, document and job (emitter wait bounded to
     5 s), counts the attempt, builds and signs the DE and stores the
     generated XML, the signed XML, the exact `rEnviDe` (real `dId`) and the
     CDC with the document in `submitting`; then it commits;
   - the worker sends that stored request unchanged (or queries the CDC, see
     below);
   - transaction 2 takes the locks in the same order: the emitter (waiting
     as long as needed, so an answer is never dropped over a busy emitter),
     then document and job, re-read with `FOR UPDATE`; then it records the
     outcome. A terminal document written meanwhile (for example by the
     `reconcile` endpoint) is never moved; a non-final outcome is dropped if
     a newer attempt already claimed the job. Status webhooks are published
     inside a savepoint: a database error while publishing is logged and
     never discards the recorded outcome.
   If the emitter lock is not granted within 5 s, no attempt is spent: the
   job keeps its status (`queued` or `retry_scheduled`), records the
   `emitter_busy` category and is dispatched again 30 s later, and the RQ job
   reports `emitters.lock_timeout`. Keeping `queued` matters for an operator
   retry of a `failed` document or event, which only a `queued` job reopens.
   Event jobs behave the same.
4. Outcomes:
   - approved/accepted => `job.succeeded`
   - request provably not sent (`SifenRequestNotSentError`) => document back
     to `queued`, `job.retry_scheduled` (`transport_not_sent`); the next
     attempt resends the stored request
   - timeout, dropped connection, SOAP Fault, unreadable answer or any other
     error after sending => document `retry_pending`, `job.retry_scheduled`
     (`transport`); later attempts only query the CDC
   - fiscal validation/rejection => `job.failed`
5. Optional webhook fanout:
   - if `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS=true`, document transitions publish
     events like `document.approved`, `document.rejected`, `document.retry_pending`
     to active subscribed webhook endpoints.

Because the payload is committed before the call, a worker that dies while
SIFEN answers leaves the document in `submitting` and the job in `processing`.
Nothing re-dispatches that job automatically yet: an operator retry (admin
console) queues it again and the next attempt queries the CDC before deciding
anything. A document that may have reached SIFEN (`submitting`, `submitted`,
`retry_pending`, `reconciliation_required`) is only ever queried by CDC: an
existing DTE converges to approved, a not-found answer (`0420`) keeps it
pending and is never resent. Automatic attempts are bounded to five; then it
becomes `reconciliation_required`, or, when SIFEN was never reached, the job
fails while the document stays `queued` for a manual retry.

## Fiscal event flow

1. API validates/signs cancelation or inutilization and creates `event` +
   `event.submit` job.
2. The `events` worker loads emitter/certificate secrets from the database; no
   secret is stored in the Redis job payload.
3. Approved cancelation moves the document to `cancelled`; approved
   inutilization stores its SIFEN protocol and publishes the terminal webhook.
4. Each attempt mirrors the document flow: transaction 1 locks emitter, event
   and job, counts the attempt and stores the signed event group and the exact
   `rEnviEventoDe` (real `dId`) with the event in `submitting`; the request is
   sent with nothing held; transaction 2 locks the emitter (unbounded wait),
   re-reads event and job `FOR UPDATE` and records the outcome (an
   `approved`/`rejected` event is never moved). Webhooks of an approved event
   are published inside a savepoint, as for documents.
5. A request that provably never left puts the event back to `queued`
   (`transport_not_sent`); any other transport failure, SOAP Fault or
   unreadable answer leaves it `retry_pending` (`transport`). Both use a
   bounded five-attempt schedule, and today both resend the stored signed
   event on the next attempt: whether an uncertain event should be queried
   first is a fiscal decision still pending. Validation/rejection is
   terminal.

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

Workers (`rq worker`) and the outbox sweeper log one JSON object per line,
with `correlation_id` when the job carries one, exactly like the API; the level
comes from `KILA_SIFEN_LOG_LEVEL`. RQ's own lifecycle lines keep RQ's text
format. Useful events: `worker.document_job.request_not_sent`,
`worker.document_job.outcome_unknown`, `worker.document_job.outcome_superseded`,
`events.outcome_unknown` and `jobs.outbox.publish_failed`.

- ratio of `failed` + `retry_scheduled` by job type
- aging of jobs in `queued`
- missing workers for any of `documents`, `events`, `webhooks`
- webhook failure concentration per endpoint
- document rejection codes from SIFEN

## References

- `docs/normativa/sifen-async-notas-tecnicas.md`
- `kilasifen/domain/common/sifen_async.py`
