# Chunk 9 - Task 24

## Goal

Run migrations and full test validation on PostgreSQL before implementing
server-side atomic numbering.

## Commit

- `b0af5e4` `feat: enable postgres-backed test isolation for local validation`

## What was changed

- PostgreSQL local runtime path prepared:
  - `docker-compose.yml` updated with explicit dev credentials for `postgres`
    service (`postgres/postgres`, db `kilasifen`, port `5432`).
- Added PostgreSQL-aware isolated test DB helper:
  - `kilasifen/testing/database.py`
  - creates per-test schemas when `KILA_SIFEN_TEST_DATABASE_URL` is set.
  - keeps SQLite fallback for fast unit flow when env var is absent.
- Updated DB-backed API/application/infrastructure tests to use the new helper
  instead of hardcoded `sqlite://...` URLs.
- Alembic migration verification test adjusted for schema-scoped PostgreSQL URLs.

## Validation

- PostgreSQL migration:
  - `KILA_SIFEN_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/kilasifen alembic upgrade head`
- Full suite against PostgreSQL:
  - `KILA_SIFEN_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/kilasifen`
  - `KILA_SIFEN_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/kilasifen`
  - `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE=false`
  - `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS=false`
  - `pytest`
- Result at close time:
  - `252 passed, 1 skipped`

## Local setup notes (dev/CI)

- Recommended local with compose:
  1. `docker compose up -d postgres`
  2. set `KILA_SIFEN_DATABASE_URL` and `KILA_SIFEN_TEST_DATABASE_URL`
     to the PostgreSQL URL.
  3. run `alembic upgrade head`
  4. run `pytest`
- In this execution environment, Docker CLI was not available, so the
  verification run used a local PostgreSQL cluster started from installed
  PostgreSQL binaries on port `55432`.
- Policy after this task:
  - SQLite: quick local tests.
  - PostgreSQL: migration checks + full suite + all concurrency-critical tests.

