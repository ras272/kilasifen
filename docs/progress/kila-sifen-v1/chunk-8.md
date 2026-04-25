# Chunk 8

## Purpose

Close the SaaS integration loop after emission:

- automatic status webhooks after document processing
- subscription-aware fanout (`exact`, `document.*`, `*`)
- operational toggles for progressive rollout

## Why it exists

Replay-only webhooks are useful for testing, but ERP production flows need push
notifications on real document state transitions without manual intervention.

## Closed tasks

- `Task 19` commit `f365807`
- `Task 20` commit `2b02e16`

## Main files

- `kilasifen/application/webhooks/service.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `kilasifen/config.py`
- `kilasifen/api/schemas/documents.py`
- `kilasifen/api/routers/documents.py`
- `tests/application/test_emission_flow.py`
- `tests/application/test_webhook_delivery.py`
- `tests/api/test_documents_api.py`
- `docs/operations/job-lifecycle.md`
