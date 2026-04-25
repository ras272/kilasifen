# Chunk 3 - Task 5

## Goal

Ship emitter management through the public HTTP API.

## Commit

- `d7eef1c` `feat: add emitter management api`

## What was created

- emitter service layer
- emitter request/response schemas
- emitter router
- create/get/update/deactivate flows
- uniqueness checks for `external_id`
- uniqueness checks for `ruc + dv`

## Endpoints added

- `POST /v1/emitters`
- `GET /v1/emitters/{emitter_id}`
- `PATCH /v1/emitters/{emitter_id}`
- `POST /v1/emitters/{emitter_id}/deactivate`

## Verification

- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_emitters_api.py tests/application/test_certificate_activation.py tests/infrastructure/test_db_foundation.py -v`
- result at close time: `12 passed`
