# Job Lifecycle

## Why this exists

Kila SIFEN is async-first for emission and outgoing integrations.
Jobs are the operational ledger for retries, observability, and support.

Nothing is pushed to RQ directly. API requests and workers write an
outbox row in the same database transaction as the job; the outbox
dispatcher (`python -m kilasifen.infrastructure.jobs.outbox_worker`)
publishes due rows to the `documents`, `events` or `webhooks` RQ queue.
Without a running dispatcher no job reaches a worker and scheduled
retries never fire.

## Core statuses

- `queued`: created and waiting execution
- `processing`: an attempt is running (committed before the SIFEN call; a
  job that stays here after its worker died needs an operator retry)
- `retry_scheduled`: transient failure, can be retried
- `succeeded`: completed successfully
- `failed`: terminal failure or non-retryable rejection

## Document emission flow

1. API creates `document` + `job` (`document.emit`) and, when
   `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE=true`, its outbox row. The setting
   defaults to `false` in code: with it off the job stays `queued` and is
   never dispatched.
2. The outbox dispatcher publishes the row to the `documents` queue.
3. Worker hydrates context:
   - emitter
   - active certificate
   - the stamping active on the emission date (`dFeEmiDE` in Paraguay time,
     not the server date); without one the document fails local validation,
     since SIFEN rejects it with 1103/1104
4. Each attempt uses two short transactions and holds no transaction or
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
5. Outcomes. The answer is classified by normalized `dEstRes` (read from
   `rProtDe` or, as the MT shows it, from `gResProc`); without `dEstRes`
   only `0260` is an approval. An approval stores `dProtAut`, every
   `gResProc` and `sifen_approved_at` (`dFecProc`).
   - approved / approved with observation => `job.succeeded`
   - answer without a recognizable `dEstRes` => document `retry_pending`,
     `job.retry_scheduled` (`sifen_unclassified`); the next attempt queries
     the CDC
   - rejected with `1001`/`1002` in any `gResProc` (their order is NO
     DETERMINADO) => document `retry_pending`
     (`duplicate_reconciliation`); the CDC is queried before the rejection is
     believed (`0422` approves it, `0420` makes the rejection final)
   - rejected with `0161`/`0162` in any `gResProc` (SIFEN server
     failures) => document
     `rejected` with `retryable_server_error`, `job.retry_scheduled`
     (`retryable_server_error`); the next attempt resends the same signed DE
   - any other rejection, or a fiscal validation failure => `job.failed`
   - request provably not sent (`SifenRequestNotSentError`) => document back
     to `queued`, `job.retry_scheduled` (`transport_not_sent`, the next
     attempt is staged in the outbox for its `scheduled_at`)
   - timeout, dropped connection, SOAP Fault, unreadable answer or any other
     error after sending => document `retry_pending`, `job.retry_scheduled`
     (`transport`, staged in the outbox for its `scheduled_at`); the next
     attempt queries the CDC
   Every resend (after `transport_not_sent`, after a `0420`, after
   `0161`/`0162`) carries the same signed DE (same CDC, signature and
   `dFecFirma`) in a new `rEnviDe` with a fresh `dId`, stored by the first
   transaction before it travels. It is signed with the certificate that was
   active when it was prepared; if the emitter certificate was rotated in
   between, the request travels over mTLS with the new certificate, and
   should SIFEN reject that, the rejection is terminal like any other.
6. Optional webhook fanout:
   - if `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS=true` (read by the worker;
     `false` by default in code), document transitions publish
     events like `document.approved`, `document.rejected`, `document.retry_pending`
     to active subscribed webhook endpoints.

Because the payload is committed before the call, a worker that dies while
SIFEN answers leaves the document in `submitting` and the job in `processing`.
Nothing re-dispatches that job automatically yet: an operator retry (admin
console) queues it again and the next attempt queries the CDC before deciding
anything. A document that may have reached SIFEN (`submitting`, `submitted`,
`retry_pending`, `reconciliation_required`) is first queried by CDC
(siConsDE): `0422` converges it to approved (or cancelled when `xContEv` holds
a registered cancellation) and it is never sent again; `0420` ("no existe o no
está aprobado") puts it back to `queued` (`resubmission`) and the next attempt
resends the same signed DE (Dto 872/2023 Art. 29; MT v150 §6.5; Guía de
Mejores Prácticas DNIT oct-2024 p. 12). The platform never sends lots, so no
pending lot can hold the CDC. Any other query code keeps querying. The copy of
the DTE in `xContenDE` never replaces `signed_xml`. Automatic attempts are
bounded to five; then a document whose CDC SIFEN never answered becomes
`reconciliation_required`, and one that is not at SIFEN (never reached, or
`0420`) stays `queued` (or `rejected` with `retryable_server_error`) while the
job fails (`retry_exhausted`) for a manual retry.

While SIFEN has not approved a document, every recorded attempt adds
`deadline_alerts` to the job `error_snapshot` and logs
`worker.document_job.transmission_deadline`: `late_transmission_soon` /
`late_transmission` around 72 h after `dFecFirma` (an approval then carries
observation 1005; Dto 872/2023 Art. 27) and `emission_rejection_soon` /
`emission_rejection` around 720 h after `dFeEmiDE` (rejection 1150). The 24 h
lead time is a platform choice.

## Fiscal event flow

1. API validates/signs cancelation or inutilization and creates `event` +
   `event.submit` job.
2. The `events` worker loads emitter/certificate secrets from the database; no
   secret is stored in the Redis job payload.
3. Only `dCodRes` `0600` registers an event. Approved cancelation moves the
   document to `cancelled`; approved inutilization stores its SIFEN protocol,
   moves the documents of the range to `inutilized` and publishes the
   terminal webhook.
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
   bounded five-attempt schedule. There is no service to query events: the
   events of a CDC come back from siConsDE in `xContEv`. So the attempt that
   follows an uncertain one queries the CDC of a cancellation first: a
   registered cancellation approves the event without sending anything; a DTE
   without cancellation lets the stored signed event travel again; `0420`
   leaves the event `reconciliation_required` (whether a cancelled DTE answers
   0420 is NO DETERMINADO); a failed query sends nothing and is tried again
   (`reconciliation_unavailable`). A `4002`/`4003`/`4009`/`4010` answer to a
   cancellation is believed only after the same query shows the DTE
   without a cancellation. `4003` (GEC002b, "ya se encuentra con un
   evento que se esta requiriendo nuevamente") is never believed: when
   `xContEv` does not show the cancellation, or any of those answers meets
   an unreadable `xContenDE`, the event becomes `reconciliation_required`.
   Before a resend an unreadable container does not stop the stored
   event: its own answer decides. An inutilization that
   gets `4066` after an uncertain attempt is left `reconciliation_required`.
   An uncertain event that exhausts its attempts becomes
   `reconciliation_required` (one that never left becomes `failed`); an
   operator retry runs the reconciliation again. Other rejections are
   terminal.
6. An event still `submitting` means an attempt stored its request and has
   recorded no outcome yet: its worker may still be waiting on SIFEN. For
   five minutes after the request was stored (the RQ job timeout is 180 s),
   a new attempt of that job (an operator retry, a duplicate dispatch) sends
   nothing: the job keeps its status, records `attempt_in_flight` and is
   dispatched again when the window closes. A `processing` job is left to
   the worker that owns it.

## Webhook delivery flow

1. Endpoint replay/event creates `webhook_delivery` + `job` (`webhook.deliver`)
   and its outbox row; the dispatcher publishes it to the `webhooks` queue.
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

A retry goes through the outbox like any dispatch. While RQ still reports a
run of the same job as `started`, the outbox does not publish it (RQ would
drop it as a duplicate): it logs `jobs.outbox.publish_deferred` and tries
again with its usual backoff (5 s, 30 s, 2 min, 10 min, 30 min). A live run
ends normally. When the worker process died, RQ keeps the record `started`
until the maintenance task of a surviving worker (every 10 minutes by
default) sees that its heartbeat expired and marks it failed, so a retry of
a dead worker's job can take that long to start.

## Recommended monitoring

Workers (`rq worker`) and the outbox sweeper log one JSON object per line,
with `correlation_id` when the job carries one, exactly like the API; the level
comes from `KILA_SIFEN_LOG_LEVEL`. RQ's own lifecycle lines keep RQ's text
format. Useful events: `worker.document_job.request_not_sent`,
`worker.document_job.outcome_unknown`, `worker.document_job.outcome_superseded`,
`events.outcome_unknown`, `events.attempt_in_flight`, `worker.job.emitter_busy`,
`jobs.outbox.publish_deferred` and `jobs.outbox.publish_failed`; fiscal
deadlines and reconciliations: `worker.document_job.transmission_deadline`,
`events.reconciliation_unavailable`, `events.inutilize.extemporaneous` and
`events.inutilize.document_changed`.

- ratio of `failed` + `retry_scheduled` by job type
- aging of jobs in `queued`
- missing workers for any of `documents`, `events`, `webhooks`
- missing outbox dispatcher: in staging/production `/v1/ready` answers 503
  with `missing:outbox_dispatcher` when its Redis heartbeat expires
- webhook failure concentration per endpoint
- document rejection codes from SIFEN

## References

- `docs/normativa/sifen-async-notas-tecnicas.md`
- `kilasifen/domain/common/sifen_async.py`
