# Chunk 10

## Purpose

Implement typed SIFEN events for MVP fiscal operations:

- document cancelation
- numbering inutilization
- numbering integration to skip approved inutilized ranges

## Why it exists

Without typed cancelation/inutilization the ERP cannot operate safely in
production. This chunk closes that gap with API contracts, XML generation, and
cross-emitter protections.

## Closed tasks

- `Task 26` commit `12407d6`

## Main files

- `kilasifen/application/events/service.py`
- `kilasifen/api/routers/events.py`
- `kilasifen/api/schemas/events.py`
- `kilasifen/infrastructure/sifen/typed_event_builder.py`
- `kilasifen/infrastructure/sifen/event.py`
- `kilasifen/infrastructure/db/repositories/document_numbering_sequences.py`
- `kilasifen/infrastructure/db/repositories/inutilized_number_ranges.py`
- `kilasifen/repositories/inutilized_number_ranges.py`
- `kilasifen/domain/events/inutilized_ranges.py`
- `alembic/versions/20260426_05_add_inutilized_number_ranges.py`
- `tests/api/test_events_api.py`
- `tests/application/test_document_numbering.py`
- `tests/infrastructure/test_db_foundation.py`
