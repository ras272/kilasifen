# Chunk 3 - Task 6

## Goal

Add encrypted certificate upload, listing, and activation.

## Commit

- `c7b1fe6` `feat: add encrypted certificate management`

## What was created

- encrypted certificate store
- certificate metadata extraction from `.p12/.pfx`
- certificate service layer
- certificate schemas
- certificate router
- upload/list/activate flows

## Security behavior

- raw certificate bytes are encrypted before persistence
- certificate password is encrypted before persistence
- read APIs return metadata only
- secrets are not exposed in API responses

## Endpoints added

- `POST /v1/emitters/{emitter_id}/certificates`
- `GET /v1/emitters/{emitter_id}/certificates`
- `POST /v1/certificates/{certificate_id}/activate`

## Verification

- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_emitters_api.py tests/api/test_certificates_api.py tests/application/test_certificate_activation.py tests/infrastructure/test_db_foundation.py tests/infrastructure/test_certificate_store.py -v`
- result at close time: `14 passed`
