# Chunk 11

## Purpose

Complete `PASO 4` for typed DE contracts:

- full typed builder for `factura_v1` and `nota_credito_v1`
- byte-exact signed XML golden coverage
- API integration tests for typed scenarios

## Why it exists

The ERP integration needs JSON -> XML SIFEN without custom XML assembly.
This chunk closes the largest MVP gap with deterministic XML output and
regression protection at signed XML level.

## Closed tasks

- `Task 27` commit `6e9a866`

## Main files

- `kilasifen/infrastructure/sifen/typed_xml_builder.py`
- `kilasifen/api/schemas/documents.py`
- `kilasifen/testing/typed_contract_scenarios.py`
- `tests/infrastructure/test_typed_xml_builder_golden.py`
- `tests/api/test_documents_typed_golden_api.py`
- `tests/golden/*.xml`
- `pysifen/sdk/signer.py`
- `tests/test_assinatura.py`
