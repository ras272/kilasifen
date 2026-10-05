# Chunk 7 - Task 16

## Goal

Strengthen CI so engine and platform regressions are visible independently, with migration and app-start smoke checks.

## Commit

- `e653705` `ci: verify kilasifen platform and engine regressions`

## What was changed

- CI workflow split into dedicated jobs:
  - `engine-regressions`
  - `platform-tests`
  - existing build/schema jobs preserved
- lint coverage added for:
  - `kilasifen/engine/` (`ruff --select F`)
  - `kilasifen/` (`ruff --select F`)
- tests split for clearer failure domains:
  - engine: root regression suite (`tests/test_*.py`)
  - platform: `tests/api`, `tests/application`, `tests/infrastructure`
- migration smoke added:
  - `alembic upgrade head` on SQLite in CI
- app bootstrap smoke added:
  - FastAPI `create_app()` + `/v1/health` and `/v1/ready` checks
- alembic runtime updated to accept `KILA_SIFEN_DATABASE_URL` override for CI environments
- small engine cleanup:
  - removed unused import in `kilasifen/engine/transmissao/de.py` uncovered by lint

## Verification

- `python -m ruff check kilasifen/engine/ --select F`
- `python -m ruff check kilasifen/ --select F`
- root engine regressions:
  - `pytest <tests/test_*.py expanded file list> -v --tb=short`
  - result: `186 passed, 1 skipped`
- platform suites:
  - `pytest tests/api tests/application tests/infrastructure -v --tb=short`
  - result: `45 passed`
- migration smoke:
  - `KILA_SIFEN_DATABASE_URL=sqlite:///./ci-migrations-local.db alembic upgrade head`
- app-start smoke:
  - TestClient health/ready checks against `create_app()`

## Notes

- `ruff` selection intentionally focuses on functional errors (`F`) to add immediate safety without blocking CI on legacy style debt

