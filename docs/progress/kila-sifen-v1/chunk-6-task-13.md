# Chunk 6 - Task 13

## Goal

Add webhook endpoint management plus signed delivery history and retry handling.

## Commit

- `7f1107e` `feat: add webhook delivery subsystem`

## What was created

- webhook domain and repository contracts
- SQLAlchemy repository for:
  - webhook endpoints
  - webhook deliveries
- application service for:
  - endpoint registration
  - endpoint listing
  - replay creation (delivery + job)
  - delivery status retrieval
  - processing delivery attempts
- signed HTTP deliverer with `X-Kila-Signature` (`sha256=<hmac>`)
- retry classification:
  - `2xx` -> delivered
  - `5xx`/transport errors -> retry_pending
  - `4xx` -> failed
- queue/worker wiring for `webhook.deliver` jobs

## Endpoints added

- `POST /v1/emitters/{emitter_id}/webhooks`
- `GET /v1/emitters/{emitter_id}/webhooks`
- `POST /v1/webhooks/{endpoint_id}/deliveries/replay`
- `GET /v1/webhook-deliveries/{delivery_id}`

## Main files

- `kilasifen/application/webhooks/service.py`
- `kilasifen/api/routers/webhooks.py`
- `kilasifen/api/schemas/webhooks.py`
- `kilasifen/infrastructure/webhooks/deliverer.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `tests/api/test_webhooks_api.py`
- `tests/application/test_webhook_delivery.py`

## Verification

- `pytest tests/api/test_webhooks_api.py tests/application/test_webhook_delivery.py -v`
- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_jobs_api.py tests/api/test_events_api.py tests/api/test_queries_api.py tests/api/test_webhooks_api.py tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py tests/infrastructure/test_rq_queue.py tests/test_eventos.py -v`
- result at close time: `28 passed`

## Notes

- queue tests still show the same upstream `rq` deprecation warning around `datetime.utcnow()`
