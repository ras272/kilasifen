# Chunk 6

## Purpose

Add operational outgoing integrations:

- webhook delivery subsystem
- admin console

## Why it exists

After emission, queries, and events are stable, external systems need reliable notifications.
This chunk introduces delivery mechanics, retries, signatures, and traceability so ERP integrations can react without polling all the time.

## Closed tasks

- `Task 13` commit `7f1107e`
- `Task 14` commit `eeca463`
- `Follow-up` commit `54d601c` (SIFEN async state machine)

## Main files

- `kilasifen/application/webhooks/service.py`
- `kilasifen/application/admin/service.py`
- `kilasifen/api/routers/webhooks.py`
- `kilasifen/admin/router.py`
- `kilasifen/admin/templates/`
- `kilasifen/api/schemas/webhooks.py`
- `kilasifen/infrastructure/webhooks/deliverer.py`
- `kilasifen/infrastructure/db/repositories/webhooks.py`
- `kilasifen/infrastructure/jobs/queue.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `kilasifen/domain/common/sifen_async.py`
