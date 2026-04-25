# Chunk 2 - Task 3

## Goal

Create the DB base, session helpers, models, and first migration.

## Commit

- `a649b57` `feat: add database foundation and initial schema`

## What was created

- SQLAlchemy base with naming convention
- session and engine helpers
- core persistence models
- Alembic config
- initial schema migration
- DB smoke tests

## Tables introduced

- `emitters`
- `api_keys`
- `certificates`
- `stampings`
- `documents`
- `jobs`
- `events`
- `webhook_endpoints`
- `webhook_deliveries`

## Verification

- `pytest tests/infrastructure/test_db_foundation.py tests/api/test_health.py -v`
- result at close time: `5 passed`
