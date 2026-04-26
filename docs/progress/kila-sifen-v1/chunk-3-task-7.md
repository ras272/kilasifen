# Chunk 3 - Task 7

## Goal

Add stamping management through the internal HTTP API consumed by the ERP.

## Commit

- `7700d80` `feat: add stamping management api`

## What was created

- stamping service layer
- stamping request/response schemas
- stamping router
- create/list/activate flows
- invalid date-window validation

## Endpoints added

- `POST /v1/emitters/{emitter_id}/stampings`
- `GET /v1/emitters/{emitter_id}/stampings`
- `POST /v1/stampings/{stamping_id}/activate`

## Verification

- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_emitters_api.py tests/api/test_certificates_api.py tests/api/test_stampings_api.py tests/application/test_certificate_activation.py tests/infrastructure/test_db_foundation.py tests/infrastructure/test_certificate_store.py -v`
- result at close time: `16 passed`
