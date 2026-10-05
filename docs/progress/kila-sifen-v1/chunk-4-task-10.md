# Chunk 4 - Task 10

## Goal

Connect the emission worker to the `kilasifen.engine` engine and persist emission artifacts plus normalized outcomes.

## Commit

- `0914799` `feat: process emission jobs through kilasifen.engine`

## What was created

- `kilasifen.engine` emission bridge under `kilasifen/infrastructure/sifen/`
- normalized `EmissionOutcome`
- payload mapper for XML-based emission inputs
- worker processing that:
  - loads emitter
  - loads active certificate
  - loads active stamping
  - decrypts certificate material
  - calls the emission engine
  - persists generated XML, signed XML, request snapshot, response snapshot, and normalized result fields

## Error categorization introduced

- fiscal validation errors
- transport/timeouts
- SIFEN rejections

These categories are persisted into `job.error_snapshot`.

## Current mapper scope

The current bridge supports document payloads that already contain XML-oriented inputs:

- `generated_xml`
- optional `signed_xml`
- optional `doc_id`

This is an intentional bridge layer so the worker can already process real emission artifacts while the higher-level fiscal payload mapping is still pending.

## Main files

- `kilasifen/infrastructure/sifen/engine.py`
- `kilasifen/infrastructure/sifen/mapper.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `kilasifen/domain/documents/models.py`
- `kilasifen/infrastructure/db/models.py`
- `kilasifen/engine/sdk/client.py`
- `kilasifen/engine/sdk/errors.py`
- `tests/application/test_emission_flow.py`

## Verification

- `pytest tests/application/test_emission_flow.py tests/test_assinatura.py tests/test_ares_de_test_xml.py tests/test_sdk_client.py -v`
- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_emitters_api.py tests/api/test_certificates_api.py tests/api/test_stampings_api.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/application/test_certificate_activation.py tests/application/test_document_idempotency.py tests/application/test_emission_flow.py tests/infrastructure/test_db_foundation.py tests/infrastructure/test_certificate_store.py tests/infrastructure/test_rq_queue.py tests/test_assinatura.py tests/test_ares_de_test_xml.py tests/test_sdk_client.py -v`
- result at close time: `50 passed`

## Notes

- the queue tests still show an upstream `rq` deprecation warning about `datetime.utcnow()`
- `tests/test_assinatura.py` still shows the same existing xsdata placeholder warnings seen before this task
