# Chunk 2 - Task 4

## Goal

Add the first domain models and repositories for emitter, certificate, and stamping logic.

## Commit

- `4269dea` `feat: add core emitter certificate and stamping domain`

## What was created

- domain models for `Emitter`
- domain models for `Certificate`
- domain models for `Stamping`
- domain errors for invariants
- repository interfaces
- SQLAlchemy repository implementations

## Invariants covered

- only one active certificate per emitter
- active stamping selection is scoped by emitter
- active stamping selection respects the date window

## Verification

- `pytest tests/application/test_certificate_activation.py tests/infrastructure/test_db_foundation.py -v`
- result at close time: `5 passed`
