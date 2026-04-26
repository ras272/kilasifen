# Chunk 9

## Purpose

Prepare the platform for reliable PostgreSQL-based validation before
implementing atomic numbering.

## Why it exists

Atomic numbering and concurrent fiscal workflows need a transactional backend
with real row-level locking semantics. SQLite is still valid for quick local
unit tests, but not for concurrency guarantees.

## Closed tasks

- `Task 24` commit `b0af5e4`

## Main files

- `docker-compose.yml`
- `kilasifen/testing/database.py`
- `tests/api/*` (database fixtures)
- `tests/application/*` (database fixtures)
- `tests/infrastructure/test_db_foundation.py`
- `tests/infrastructure/test_rq_queue.py`

