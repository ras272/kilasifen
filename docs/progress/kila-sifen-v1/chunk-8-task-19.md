# Chunk 8 - Task 19

## Goal

Emit webhook deliveries automatically when a document job transitions to a terminal
state, so ERP consumers receive push updates without manual replay.

## Commit

- recorded after merge in main history (`git log -- docs/progress/kila-sifen-v1/chunk-8-task-19.md`)

## What was changed

- `WebhookService` now supports event publication fanout by emitter:
  - `publish_document_status(document=...)`
  - `publish_event(emitter_id, event_type, payload)`
- endpoint subscription matching now supports:
  - exact event (`document.approved`)
  - wildcard domain (`document.*`)
  - global wildcard (`*`)
  - `None`/empty subscription as catch-all
- document worker can publish these events post-emission when enabled:
  - `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS=true`
- queue fanout keeps async delivery model (`webhook.deliver` jobs).

## Validation

- `pytest tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py tests/api/test_webhooks_api.py tests/api/test_documents_api.py tests/api/test_jobs_api.py -v`
- `python -m ruff check kilasifen/application/webhooks/service.py kilasifen/infrastructure/jobs/workers.py kilasifen/config.py tests/application/test_emission_flow.py tests/application/test_webhook_delivery.py --select F`
- result at close time: `13 passed`, `ruff: All checks passed`

## Notes

- this behavior is feature-flagged for safe rollout in mixed environments.
