# Chunk 7 - Task 17

## Goal

Provide an executable E2E smoke runner that tells quickly if Kila API is operational end-to-end.

## Commit

- `bbc460f` `feat: add e2e smoke runner for kila api`

## What was created

- `docs/examples/smoke_kila_api_e2e.py`

Main checks implemented:

- `/v1/health` and `/v1/ready`
- emitter existence or creation
- active certificate presence (or upload + activation)
- active stamping presence (or create + activation)
- document creation (`/v1/emitters/{id}/documents`)
- job convergence polling (`/v1/jobs/{id}`)
- document terminal state validation (`/v1/documents/{id}`)
- optional webhook replay check (`--webhook-endpoint-id`)

Output contract:

- prints per-step `PASS/FAIL`
- prints final `OVERALL: PASS` or `OVERALL: FAIL`
- exits `0` on pass, non-zero on failure

## Validation

- `python docs/examples/smoke_kila_api_e2e.py --help`
- `python -m py_compile docs/examples/smoke_kila_api_e2e.py`
- `python -m ruff check docs/examples/smoke_kila_api_e2e.py --select F`
- result at close time: all passed

