# Chunk 16 - Task 31

## Commit

- `31b9cc3`

## What changed

- kept `fecha_emision` in Paraguay local wall time instead of converting aware
  timestamps to naive UTC before signing
- required `cliente.numero_casa` when `cliente.direccion` is informed, instead
  of inventing a fake house number in the XML
- normalized real SIFEN rejections from `rProtDe.gResProc` so rejected DEs are
  persisted as `document_status=rejected` / `job_status=failed`
- persisted the CDC even when SIFEN rejects the DE
- aligned typed factura/NC totals with the real SIFEN rules used in TEST:
  no `dTotOpeGs` or `dTotalGs` for PYG, no duplicated `dLiqTotIVA5/10`,
  and IVA/base values rounded to guaranies where SIFEN expects integer fiscal
  amounts
- regenerated signed XML goldens after the fiscal XML changes

## Verification

- `python -m pytest -q`
  - result: `355 passed, 5 skipped`
- `python -m ruff check --select I,F kilasifen/infrastructure/sifen/typed_xml_builder.py kilasifen/infrastructure/sifen/engine.py kilasifen/infrastructure/jobs/workers.py tests/infrastructure/test_typed_xml_builder.py tests/infrastructure/test_sifen_engine.py tests/application/test_emission_flow.py`
  - result: `All checks passed!`
- real SIFEN TEST smoke:
  - emitter: `80024135-5`
  - result code: `0260`
  - message: `Autorización del DE satisfactoria`
  - approved CDC: `01800241355001001000000722026042611234567895`
- post-approval API checks:
  - `GET /v1/emitters/{emitter_id}/documents/{document_id}/xml` -> `200`
  - `GET /v1/emitters/{emitter_id}/documents/{document_id}/kude/data` -> `200`
  - `GET /v1/emitters/{emitter_id}/documents/{document_id}/kude` -> `200`

## Notes

- the end-to-end debug path moved through real SIFEN codes `1004 -> 1330 -> 1858 -> 2389 -> 2371 -> 0260`
- this task intentionally documents the smoke-tested approved document so the
  next debugging session can start from an approved baseline, not from old
  rejected hypotheses
