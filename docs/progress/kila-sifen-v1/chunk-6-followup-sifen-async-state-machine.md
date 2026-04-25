# Chunk 6 - Follow-up: SIFEN Async State Machine

## Goal

Codify async SIFEN response handling into a reusable state machine instead of ad-hoc if/else logic.

## Commit

- `54d601c` `feat: add sifen async state machine rules`

## What was created

- async operation enums for:
  - `recibe_lote`
  - `consulta_lote`
  - `consulta_cdc`
- normalized decision model with:
  - state
  - action
  - terminal flag
  - retry recommendation
  - minimum retry delay
- transition guard that raises domain invariant errors on invalid flows
- lot-detail status mapper for `gResProcLote.dEstRes`
- anti-duplicate helper for CDC resend policy

## Main files

- `kilasifen/domain/common/sifen_async.py`
- `tests/application/test_sifen_async_state_machine.py`

## Verification

- `pytest tests/application/test_sifen_async_state_machine.py -v`
- `pytest tests/application/test_sifen_async_state_machine.py tests/api/test_events_api.py tests/api/test_webhooks_api.py tests/application/test_webhook_delivery.py -v`
- result at close time: `14 passed`

## Notes

- this module is intentionally domain-only so workers/services can consume it without coupling to transport adapters
