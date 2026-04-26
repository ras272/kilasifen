# Chunk 11 - Task 27

## Goal

Implement `PASO 4` for typed document builders:

- complete typed payload support for `factura` and `nota_credito`
- remove fragile XML-only assumptions for ERP-side requests
- lock behavior with signed XML goldens (byte-exact)

## Commit

- `6e9a866` `feat: complete typed factura/nc builders with signed xml goldens`

## What was changed

- Expanded typed API contracts:
  - `FacturaContractPayload`
  - `NotaCreditoContractPayload`
- Reworked typed XML builder with:
  - invoice/credit-note specific groups (`E1`, `E5`, `H`)
  - IVA affectation/tax/base/liquidation calculations per item
  - document totals validation and consistency checks
  - payment condition handling (contado/credito)
  - associated document handling for NC
  - signed-XML safety guards (`ds:` prefix, comments, whitespace)
- Added reusable typed scenarios source:
  - `kilasifen/testing/typed_contract_scenarios.py`
- Added golden tests for 12 scenarios:
  - 9 factura scenarios
  - 3 nota credito scenarios
- Added API integration tests to verify:
  - endpoint creation
  - signed XML equality vs golden snapshots
  - server-side numbering progression
  - cross-emitter isolation on XML download
- Fixed signer ordering regression:
  - ensures `Signature` is emitted before `gCamFuFD` at root level
  - covered by dedicated signer regression test

## Golden coverage

- `factura_b2b_iva10.xml`
- `factura_b2c_iva_mixto.xml`
- `factura_descuento_global.xml`
- `factura_anticipo.xml`
- `factura_credito_cuotas.xml`
- `factura_pago_tarjeta.xml`
- `factura_pago_cheque.xml`
- `factura_moneda_usd.xml`
- `factura_b2g.xml`
- `nc_total.xml`
- `nc_parcial.xml`
- `nc_motivo_descuento.xml`

## Validation

- `python -m pytest tests/infrastructure/test_typed_xml_builder_golden.py -q`
- `python -m pytest tests/api/test_documents_typed_golden_api.py -q`
- `python -m pytest tests/test_assinatura.py -q`
- `python -m pytest -q`

Results:

- `13 passed` (builder goldens)
- `12 passed` (typed API goldens)
- `13 passed` (signature suite)
- `293 passed, 5 skipped` (full suite)

## Notes

- Golden snapshots are generated from signed XML and committed as source of
  truth for byte-level regressions.
- Test parity required deterministic emitter fields in API integration tests;
  otherwise byte-equality fails despite semantically valid XML.
