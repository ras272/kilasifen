# Chunk 7 - Task 15

## Goal

Document the platform and provide a runnable local deployment path for ERP integration.

## Commit

- `b714360` `docs: add platform deployment and integration guidance`

## What was created

- local stack definitions:
  - `docker-compose.yml`
  - `.env.example`
- platform architecture and operations docs:
  - `docs/architecture/kila-platform.md`
  - `docs/operations/deployment-compose.md`
  - `docs/operations/job-lifecycle.md`
- ERP-oriented API usage examples:
  - `docs/examples/kila_api_register_certificate.py`
  - `docs/examples/kila_api_emit_document.py`
- public docs updates:
  - README section separating `pysifen` engine and `kilasifen` platform
  - `docs/architecture/public-api.md` updated with platform-doc pointers

## Verification

- `pytest tests/api/test_health.py -v`
- `docker compose config -q` attempted for compose syntax smoke
- result at close time:
  - `2 passed` (health/ready smoke)
  - docker CLI unavailable in this environment (`docker: command not found`)

## Notes

- compose and env template are ready for local run on machines with Docker installed

