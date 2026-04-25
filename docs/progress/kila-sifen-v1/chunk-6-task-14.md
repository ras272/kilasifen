# Chunk 6 - Task 14

## Goal

Ship a first operational admin console with read-heavy screens and low-risk operator actions.

## Commit

- `eeca463` `feat: add operational admin console`

## What was created

- server-rendered admin router under `/admin`
- templates for:
  - emitters list
  - emitter operational detail
  - documents list
  - jobs list
  - webhook failures list
- admin application service to compose read models from repositories
- low-risk actions:
  - activate certificate
  - retry supported jobs (`document.emit`, `webhook.deliver`)
- repository read extensions for console lists:
  - emitters
  - recent documents
  - recent jobs
  - recent webhook deliveries
- queue payload fix:
  - document enqueue now includes `encryption_key` required by worker

## Main files

- `kilasifen/admin/router.py`
- `kilasifen/admin/templates/base.html`
- `kilasifen/admin/templates/emitters/list.html`
- `kilasifen/admin/templates/emitter_detail.html`
- `kilasifen/admin/templates/documents/list.html`
- `kilasifen/admin/templates/jobs/list.html`
- `kilasifen/admin/templates/webhooks/list.html`
- `kilasifen/application/admin/service.py`
- `kilasifen/api/deps.py`
- `kilasifen/api/app.py`
- `tests/api/test_admin_console.py`

## Verification

- `pytest tests/api/test_admin_console.py tests/infrastructure/test_rq_queue.py -v`
- `pytest tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_webhooks_api.py -v`
- result at close time: `10 passed`

## Notes

- global `ruff` still reports legacy issues in untouched files, so linting remains scoped to changed surfaces until Chunk 7 CI hardening

