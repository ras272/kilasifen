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
- `Task 21` commit `11b8f2e`
- `Task 22` commit `TBD`

## Main files

- `kilasifen/application/webhooks/service.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `kilasifen/config.py`
- `kilasifen/api/schemas/documents.py`
- `kilasifen/api/routers/documents.py`
- `kilasifen/api/routers/jobs.py`
- `kilasifen/api/routers/webhooks.py`
- `kilasifen/api/routers/emitters.py`
- `kilasifen/infrastructure/sifen/typed_xml_builder.py`
- `kilasifen/infrastructure/sifen/mapper.py`
- `kilasifen/application/emitters/health.py`
- `tests/application/test_emission_flow.py`
- `tests/application/test_webhook_delivery.py`
- `tests/api/test_documents_api.py`
- `tests/api/test_jobs_api.py`
- `tests/api/test_webhooks_api.py`
- `tests/api/test_emitters_api.py`
- `tests/infrastructure/test_typed_xml_builder.py`
- `docs/operations/job-lifecycle.md`
