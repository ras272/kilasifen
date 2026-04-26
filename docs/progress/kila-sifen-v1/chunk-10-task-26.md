# Chunk 10 - Task 26

## Goal

Implement typed events for:

- `POST /v1/emitters/{emitter_id}/documents/{document_id}/cancel`
- `POST /v1/emitters/{emitter_id}/inutilizations`

with fiscal validations, persistence for inutilized ranges, and numbering
integration to skip approved inutilized numbers.

## Commit

- `12407d6` `feat: add typed cancel and inutilization events`

## What was changed

- Added typed event XML builder for cancelation and inutilization:
  - `kilasifen/infrastructure/sifen/typed_event_builder.py`
  - signs XML and validates against WS/event bindings before submit.
- Expanded `EventService` with typed workflows and validations:
  - cancelation deadlines by document type
  - already-cancelled detection
  - child DTE guard (no auto-cascade)
  - inutilization range validation (`<= 1000`, overlap checks, conservative
    deadline rule)
  - webhook publish on approved outcomes:
    `document.cancelled`, `numbering.inutilized`.
- Added persistence for approved inutilization tracking:
  - new domain model + repository contract/SQLAlchemy implementation
  - migration `20260426_05` with `inutilized_number_ranges` table + tuple index.
- Integrated numbering reservation with approved inutilized ranges:
  - `reserve_next_number` now skips over approved ranges in the same
    transaction lock.
- Extended repository contracts needed for validations:
  - document lookup by CDC and associated CDC links
  - list numbers in range
  - event list by `(document_id, type, status)`.
- Added API contract/error support:
  - typed request schemas for cancelation/inutilization
  - `UnprocessableEntityError` (`422`) support
  - structured conflict details in error payload.
- Added/updated tests for:
  - cancelation and inutilization API paths (including cross-emitter isolation)
  - numbering behavior skipping approved inutilized ranges
  - DB foundation table coverage.

## Validation

- Focused validation:
  - `python -m pytest tests/api/test_events_api.py tests/application/test_document_numbering.py tests/infrastructure/test_db_foundation.py -q`
  - result: `24 passed`
- Full suite on PostgreSQL:
  - `python -m pytest -q`
  - result: `272 passed, 1 skipped`
- Determinism evidence:
  - concurrency and skip-range tests execute 5 iterations per run:
    - `test_reserve_next_number_concurrency_is_deterministic`
    - `test_reserve_next_number_skips_approved_inutilized_ranges`

## Notes

- API tests use a mocked typed XML builder to avoid requiring real PKCS12 files
  in endpoint tests; XML validation and signing remain covered at builder/service
  layer boundaries.
- Manual text mentions `dTiGDE` for event payload, but current
  `pysifen.bindings.evento_v150` path used by the gateway validates the
  implemented structure without that explicit node. This needs confirmation when
  upgrading bindings/spec source.
