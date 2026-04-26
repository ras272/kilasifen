# Chunk 9 - Task 25

## Goal

Implement always-on server-side atomic numbering for typed document builders
(`factura`, `nota_credito`) with PostgreSQL-safe concurrency behavior.

## Commit

- `a241da7` `feat: add server-side atomic numbering for typed documents`

## What was changed

- Added domain/repository/service layer for numbering sequences:
  - `kilasifen/domain/documents/numbering.py`
  - `kilasifen/repositories/document_numbering_sequences.py`
  - `kilasifen/application/documents/numbering_service.py`
- Added persistence model + migration:
  - `document_numbering_sequences` table with unique tuple
    `(emitter_id, establishment, point, document_type)`
  - new `documents` fields:
    `establishment`, `point`, `document_number`
  - unique constraint in `documents` by
    `(emitter_id, document_type, establishment, point, document_number)`
  - files:
    - `kilasifen/infrastructure/db/models.py`
    - `alembic/versions/20260426_04_add_document_numbering_sequences.py`
- Implemented transactional reservation with lock semantics:
  - `SqlAlchemyDocumentNumberingSequenceRepository.reserve_next_number(...)`
  - PostgreSQL path uses row locking (`SELECT ... FOR UPDATE`)
  - PostgreSQL lock timeout surfaces as `ServiceUnavailableError`
    (`numbering.lock_timeout`)
- Integrated numbering into document creation flow:
  - `kilasifen/application/documents/service.py`
  - typed payload `numero` from client is ignored
  - warning log event:
    `documents.numbering.client_number_ignored`
  - reserved number is persisted in both `payload_snapshot` and `Document`.
- Added API mapping for transient numbering lock errors:
  - `ServiceUnavailableError` -> HTTP `503`
  - files:
    - `kilasifen/domain/common/errors.py`
    - `kilasifen/api/errors.py`
    - `kilasifen/api/app.py`
- Updated API schemas and DI wiring:
  - number is no longer required in typed payload validators
  - response now exposes `establishment`, `point`, `document_number`
  - files:
    - `kilasifen/api/schemas/documents.py`
    - `kilasifen/api/deps.py`

## Fiscal behavior (explicit)

- Reserved numbers are **never released**.
- If emission fails after reservation, that number remains consumed.
- This is intentional and required for fiscal traceability.
- Any numbering gaps must be handled with inutilizacion events, not rollback.

## Validation

- Migration applied on PostgreSQL:
  - `KILA_SIFEN_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/kilasifen`
  - `alembic upgrade head`
- Targeted tests:
  - `pytest tests/application/test_document_numbering.py tests/api/test_documents_api.py tests/infrastructure/test_db_foundation.py -q`
  - result: `17 passed`
- Full suite on PostgreSQL:
  - `pytest -q`
  - result: `256 passed, 1 skipped`
- Concurrency determinism evidence (critical test):
  - `pytest tests/application/test_document_numbering.py::test_reserve_next_number_concurrency_is_deterministic -q`
  - executed `5` consecutive runs
  - all `5/5` runs passed

## Notes

- Docker CLI was unavailable in this execution environment.
- PostgreSQL verification was executed with a temporary local PostgreSQL cluster
  started from installed PostgreSQL binaries on port `55432`.
