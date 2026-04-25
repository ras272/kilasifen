# Chunk 7

## Purpose

Raise DX and deployment readiness for the platform:

- runnable local stack
- integration examples for ERP usage
- CI visibility split between engine and platform

## Why it exists

After core API/jobs/webhooks/admin, the next bottleneck is operational adoption.
Chunk 7 turns implementation into a reproducible developer product with deployment docs and stronger automated verification.

## Closed tasks

- `Task 15` commit `b714360`
- `Task 16` commit `e653705`
- `Task 17` commit `bbc460f`

## Main files

- `docker-compose.yml`
- `.env.example`
- `docs/architecture/kila-platform.md`
- `docs/operations/deployment-compose.md`
- `docs/operations/job-lifecycle.md`
- `docs/examples/kila_api_register_certificate.py`
- `docs/examples/kila_api_emit_document.py`
- `.github/workflows/tests.yml`
- `alembic/env.py`
- `docs/examples/smoke_kila_api_e2e.py`
