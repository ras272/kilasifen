# Chunk 5

## Purpose

Expand the source-of-truth side of the platform:

- SIFEN queries
- fiscal events

## Why it exists

By this point the platform can emit and track documents, but it still needs read-side workflows to:

- query taxpayer data from SIFEN
- re-check document status from SIFEN
- persist operational evidence when a query matters

This chunk starts turning Kila SIFEN into a fuller fiscal control plane instead of only an emission path.

## Closed tasks

- `Task 11` commit `7373379`
- `Task 12` commit `afdf4a9`

## Main files

- `kilasifen/application/queries/service.py`
- `kilasifen/api/routers/queries.py`
- `kilasifen/api/schemas/queries.py`
- `kilasifen/infrastructure/sifen/query.py`
- `kilasifen/domain/documents/models.py`
- `kilasifen/infrastructure/db/models.py`
- `alembic/versions/20260424_02_add_document_query_traces.py`
- `kilasifen/application/events/service.py`
- `kilasifen/api/routers/events.py`
- `kilasifen/api/schemas/events.py`
- `kilasifen/infrastructure/sifen/event.py`
- `alembic/versions/20260424_03_add_event_transport_traces.py`
- `tests/api/test_events_api.py`
