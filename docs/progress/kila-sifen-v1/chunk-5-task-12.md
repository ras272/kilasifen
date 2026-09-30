# Chunk 5 - Task 12

## Goal

Add fiscal event workflows over existing documents and persist normalized SIFEN outcomes.

## Commit

- `afdf4a9` `feat: add fiscal event workflows`

## What was created

- event domain model and repository contract
- SQLAlchemy repository for events
- event service layer (`router -> service -> repository`) with:
  - emitter/document/certificate validations
  - event record creation
  - job creation (`event.submit`)
  - event submission through `kilasifen.engine`
  - normalized success/failure status mapping
- `kilasifen.engine`-backed event gateway
- API contracts and routes for create/get event
- event transport traces persisted in DB:
  - `sifen_request_xml`
  - `sifen_response_raw`

## Endpoints added

- `POST /v1/emitters/{emitter_id}/events`
- `GET /v1/events/{event_id}`

## Main files

- `kilasifen/application/events/service.py`
- `kilasifen/api/routers/events.py`
- `kilasifen/api/schemas/events.py`
- `kilasifen/infrastructure/sifen/event.py`
- `kilasifen/infrastructure/db/repositories/events.py`
- `kilasifen/domain/events/models.py`
- `tests/api/test_events_api.py`

## Verification

- `pytest tests/api/test_events_api.py tests/test_eventos.py -v`
- `pytest tests/api/test_health.py tests/api/test_api_keys.py tests/api/test_documents_api.py tests/api/test_jobs_api.py tests/api/test_queries_api.py tests/api/test_events_api.py tests/application/test_document_idempotency.py tests/application/test_emission_flow.py tests/infrastructure/test_db_foundation.py tests/infrastructure/test_rq_queue.py -v`
- result at close time: `22 passed`

## Notes

- queue tests still show the same upstream `rq` deprecation warning around `datetime.utcnow()`
