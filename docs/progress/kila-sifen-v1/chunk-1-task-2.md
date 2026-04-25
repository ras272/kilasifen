# Chunk 1 - Task 2

## Goal

Add common API envelopes and API key authentication.

## Commit

- `41de026` `feat: add api key auth and response envelopes`

## What was created

- `X-API-Key` validation path
- `correlation_id` per request
- standard success envelope
- standard error envelope
- structured exception mapping
- contract doc in `docs/architecture/kila-api-contract.md`
- auth tests in `tests/api/test_api_keys.py`

## Main files

- `kilasifen/api/app.py`
- `kilasifen/api/deps.py`
- `kilasifen/api/errors.py`
- `kilasifen/api/schemas/common.py`
- `kilasifen/security.py`

## Verification

- `pytest tests/api/test_health.py tests/api/test_api_keys.py -v`
- result at close time: `5 passed`
