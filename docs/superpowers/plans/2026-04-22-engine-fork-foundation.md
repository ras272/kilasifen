# Pysifen Fork Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current repository into a production-ready foundation for a stable SIFEN SDK, while preserving the generated-binding strategy.

**Architecture:** Keep generated XSD bindings as low-level internals and build a narrow product layer above them. Fix correctness and operational gaps first, then add ergonomics, then expand toward a gateway/API service.

**Tech Stack:** Python 3.12+, xsdata, lxml, cryptography, signxml, requests, pytest, ruff

---

## File Map

### New files to create

- `docs/architecture/public-api.md`
- `docs/architecture/schema-version-policy.md`
- `docs/operations/transport-behavior.md`
- `docs/examples/send_factura_sync.py`
- `docs/examples/send_lote.py`
- `kilasifen/engine/sdk/__init__.py`
- `kilasifen/engine/sdk/client.py`
- `kilasifen/engine/sdk/errors.py`
- `kilasifen/engine/sdk/validation.py`
- `kilasifen/engine/sdk/signatures.py`
- `kilasifen/engine/builders/__init__.py`
- `kilasifen/engine/builders/factura.py`
- `kilasifen/engine/helpers/__init__.py`
- `kilasifen/engine/helpers/cdc.py`
- `kilasifen/engine/helpers/qr.py`
- `tests/test_public_api.py`
- `tests/test_validation.py`
- `tests/test_errors.py`
- `tests/test_sdk_client.py`
- `tests/test_polling.py`
- `tests/test_builders.py`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `SECURITY.md`

### Existing files to modify

- `kilasifen/engine/__init__.py`
- `kilasifen/engine/CommonMixin.py`
- `kilasifen/engine/assinatura.py`
- `kilasifen/engine/transmissao/base.py`
- `kilasifen/engine/transmissao/de.py`
- `kilasifen/engine/transmissao/consulta.py`
- `kilasifen/engine/transmissao/evento.py`
- `README.md`
- `pyproject.toml`
- `.github/workflows/tests.yml`
- `tests/test_transmissao.py`
- `tests/test_generate_de.py`

### Existing assets to expand

- `kilasifen/engine/de/samples/v150/`

---

## Chunk 1: Public API And Error Model

### Task 1: Define the stable facade

**Files:**
- Create: `docs/architecture/public-api.md`
- Modify: `kilasifen/engine/__init__.py`
- Create: `tests/test_public_api.py`

- [ ] Step 1: Write facade documentation describing the supported top-level imports.
- [ ] Step 2: Write failing tests that import the intended public API surface from `kilasifen.engine`.
- [ ] Step 3: Expose only the approved high-level symbols in `kilasifen/engine/__init__.py`.
- [ ] Step 4: Run `pytest tests/test_public_api.py -v`.
- [ ] Step 5: Update `README.md` examples to use the new public facade.
- [ ] Step 6: Commit with message `feat: add stable public api facade`.

### Task 2: Introduce typed errors

**Files:**
- Create: `kilasifen/engine/sdk/errors.py`
- Create: `tests/test_errors.py`
- Modify: `kilasifen/engine/transmissao/base.py`
- Modify: `kilasifen/engine/assinatura.py`

- [ ] Step 1: Write failing tests for transport, signature, and validation error classes.
- [ ] Step 2: Add error types for schema, signature, transport, timeout, and SIFEN rejection cases.
- [ ] Step 3: Wrap low-level exceptions into typed domain errors at the SDK boundary.
- [ ] Step 4: Run `pytest tests/test_errors.py -v`.
- [ ] Step 5: Commit with message `feat: add typed sdk errors`.

---

## Chunk 2: Validation Correctness And Schema Registry

### Task 3: Replace heuristic validation

**Files:**
- Create: `kilasifen/engine/sdk/validation.py`
- Modify: `kilasifen/engine/CommonMixin.py`
- Create: `tests/test_validation.py`

- [ ] Step 1: Write a failing test that validates `factura_electronica.xml` successfully through the public API.
- [ ] Step 2: Write a failing test for an intentionally invalid XML case.
- [ ] Step 3: Define a checked-in validation matrix that maps each supported root class or root tag to an exact XSD entrypoint.
- [ ] Step 4: Add caching for compiled `lxml.etree.XMLSchema` objects.
- [ ] Step 5: Refactor `CommonMixin.validate_xml()` to delegate to the registry.
- [ ] Step 6: Run `pytest tests/test_validation.py tests/test_generate_de.py -v`.
- [ ] Step 7: Document the version/schema mapping and unknown-root behavior in `docs/architecture/schema-version-policy.md`.
- [ ] Step 8: Commit with message `fix: make xml validation deterministic`.

### Task 4: Reduce parser/serializer churn

**Files:**
- Modify: `kilasifen/engine/CommonMixin.py`
- Modify: `tests/test_de.py`

- [ ] Step 1: Add a failing regression test for repeated parse/serialize calls.
- [ ] Step 2: Introduce reusable parser and serializer factories or caches where safe.
- [ ] Step 3: Replace deprecated serializer settings if needed to avoid warnings.
- [ ] Step 4: Run `pytest tests/test_de.py tests/test_generate_de.py -v`.
- [ ] Step 5: Commit with message `perf: reuse xml parser and serializer objects`.

---

## Chunk 3: Transport Hardening

### Task 5: Introduce explicit transport lifecycle

**Files:**
- Modify: `kilasifen/engine/transmissao/base.py`
- Create: `docs/operations/transport-behavior.md`
- Modify: `tests/test_transmissao.py`

- [ ] Step 1: Write failing tests for explicit cleanup and context-manager usage.
- [ ] Step 2: Define and document ownership rules for session state, temporary certificate files, and idempotent `close()`.
- [ ] Step 3: Add `close()` and context-manager support to the transport/client lifecycle.
- [ ] Step 4: Make requests after `close()` fail with a typed error.
- [ ] Step 5: Run `pytest tests/test_transmissao.py -v`.
- [ ] Step 6: Document transport lifecycle behavior.
- [ ] Step 7: Commit with message `refactor: add explicit transport lifecycle`.
- [ ] Step 8: Keep `__del__` only as a defensive fallback if still needed.

### Task 6: Add timeouts, retries, and session reuse

**Files:**
- Modify: `kilasifen/engine/transmissao/base.py`
- Modify: `kilasifen/engine/transmissao/de.py`
- Modify: `kilasifen/engine/transmissao/consulta.py`
- Modify: `kilasifen/engine/transmissao/evento.py`
- Modify: `tests/test_transmissao.py`

- [ ] Step 1: Write failing tests for request timeout configuration and retry behavior.
- [ ] Step 2: Reuse a single configured session/transport per client instance.
- [ ] Step 3: Ensure retries reuse existing certificate/session state rather than rebuilding it on every attempt.
- [ ] Step 4: Add configurable timeouts and a conservative retry policy for retryable failures.
- [ ] Step 5: Ensure non-retryable protocol/domain failures surface immediately.
- [ ] Step 6: Run `pytest tests/test_transmissao.py -v`.
- [ ] Step 7: Commit with message `feat: add retries timeouts and session reuse`.

### Task 7: Reuse certificate and signing state

**Files:**
- Create: `kilasifen/engine/sdk/signatures.py`
- Modify: `kilasifen/engine/assinatura.py`
- Modify: `kilasifen/engine/transmissao/base.py`
- Modify: `tests/test_assinatura.py`

- [ ] Step 1: Write failing tests for repeated signatures using a reusable signer object.
- [ ] Step 2: Extract PKCS12 parsing into a reusable signer/service layer.
- [ ] Step 3: Make `assinatura.sign_xml()` delegate to the reusable signer path.
- [ ] Step 4: Update transmission signing flow to use the signer service.
- [ ] Step 5: Run `pytest tests/test_assinatura.py tests/test_transmissao.py -v`.
- [ ] Step 6: Commit with message `perf: reuse signer and certificate material`.

---

## Chunk 4: SDK Layer And Ergonomics

### Task 8: Build the first SDK client

**Files:**
- Create: `kilasifen/engine/sdk/__init__.py`
- Create: `kilasifen/engine/sdk/client.py`
- Create: `tests/test_sdk_client.py`
- Modify: `README.md`

- [ ] Step 1: Write failing tests for a high-level client API wrapping send/query operations.
- [ ] Step 2: Implement `SifenClient` as the stable high-level entrypoint.
- [ ] Step 3: Keep the first version intentionally small: send DE, send lote, query DE, query lote, query RUC, send event.
- [ ] Step 4: Run `pytest tests/test_sdk_client.py -v`.
- [ ] Step 5: Update README quickstart to use `SifenClient`.
- [ ] Step 6: Commit with message `feat: add sdk client facade`.

### Task 9: Add first builder and helper utilities

**Files:**
- Create: `kilasifen/engine/builders/__init__.py`
- Create: `kilasifen/engine/builders/factura.py`
- Create: `kilasifen/engine/helpers/__init__.py`
- Create: `kilasifen/engine/helpers/cdc.py`
- Create: `kilasifen/engine/helpers/qr.py`
- Create: `tests/test_builders.py`

- [ ] Step 1: Write failing tests for a minimal factura builder flow.
- [ ] Step 2: Write failing tests for CDC helper output using a fixed documented fixture.
- [ ] Step 3: Write failing tests for QR helper output using a fixed documented fixture and expected URL shape.
- [ ] Step 4: Document the exact input and output contracts for CDC and QR helpers before implementation.
- [ ] Step 5: Implement only the minimum builder path for a normal factura.
- [ ] Step 6: Implement CDC and QR helpers according to the documented contract and official manual.
- [ ] Step 7: Run `pytest tests/test_builders.py -v`.
- [ ] Step 8: Commit with message `feat: add factura builder and helpers`.

### Task 10: Add executable docs examples

**Files:**
- Create: `docs/examples/send_factura_sync.py`
- Create: `docs/examples/send_lote.py`
- Modify: `README.md`

- [ ] Step 1: Write the two example scripts using only the stable public facade.
- [ ] Step 2: Add a minimal smoke test or import/run check for both scripts.
- [ ] Step 3: Link the examples from `README.md`.
- [ ] Step 4: Run the smoke check for the examples.
- [ ] Step 5: Commit with message `docs: add executable examples`.

---

## Chunk 5: Functional Coverage Expansion

### Task 11: Cover all 8 DE types with samples and tests

**Files:**
- Modify: `kilasifen/engine/de/samples/v150/`
- Modify: `tests/test_de.py`
- Modify: `tests/test_generate_de.py`

- [ ] Step 1: Inventory current coverage for types 1, 2, 3, 4, 5, 6, 7, and 8.
- [ ] Step 2: Confirm that current fixtures already cover 1, 4, 5, and 7.
- [ ] Step 3: Add missing XML samples for 2, 3, 6, and 8.
- [ ] Step 4: Add parsing tests for each newly added sample.
- [ ] Step 5: Add round-trip tests for every sample-backed DE type.
- [ ] Step 6: Run `pytest tests/test_de.py tests/test_generate_de.py -v`.
- [ ] Step 7: Commit with message `test: cover all document types`.

### Task 12: Expose async/polling helpers for lote and DTE workflows

**Files:**
- Modify: `kilasifen/engine/sdk/client.py`
- Modify: `kilasifen/engine/transmissao/consulta.py`
- Create: `tests/test_polling.py`

- [ ] Step 1: Write failing tests for polling lote and DTE async flows.
- [ ] Step 2: Add helpers that encapsulate polling semantics with explicit stop conditions.
- [ ] Step 3: Ensure polling settings are configurable and safe by default.
- [ ] Step 4: Run `pytest tests/test_polling.py -v`.
- [ ] Step 5: Commit with message `feat: add polling helpers for async workflows`.

---

## Chunk 6: Open Source Readiness

### Task 13: Improve package identity and repository docs

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Create: `CONTRIBUTING.md`
- Create: `CHANGELOG.md`
- Create: `SECURITY.md`

- [ ] Step 1: Resolve the package naming story between `sifen` and `kilasifen.engine` in docs and metadata.
- [ ] Step 2: Add contributor guidance and release notes skeleton.
- [ ] Step 3: Add a basic security disclosure policy.
- [ ] Step 4: Run `python -m build` after adding build dependencies.
- [ ] Step 5: Commit with message `docs: improve package identity and oss governance`.

### Task 14: Strengthen CI

**Files:**
- Modify: `.github/workflows/tests.yml`

- [ ] Step 1: Add wheel/sdist build verification to CI.
- [ ] Step 2: Add a focused smoke test for top-level imports.
- [ ] Step 3: Add warnings-as-signal checks where practical.
- [ ] Step 4: Run the equivalent local commands where available.
- [ ] Step 5: Commit with message `ci: verify artifacts and public api smoke tests`.

---

## Suggested Execution Order

1. Chunk 1
2. Chunk 2
3. Chunk 3
4. Chunk 4
5. Chunk 5
6. Chunk 6

Do not start builders or new API ergonomics before validation and transport hardening are in place.
Do not start the future API/gateway track from this plan.

## Verification Commands

- `pytest tests/test_public_api.py -v`
- `pytest tests/test_validation.py -v`
- `pytest tests/test_errors.py -v`
- `pytest tests/test_assinatura.py tests/test_transmissao.py -v`
- `pytest tests/test_sdk_client.py -v`
- `pytest tests/test_polling.py -v`
- `pytest tests/test_de.py tests/test_generate_de.py -v`
- `pytest tests -v --tb=short`
- `ruff check kilasifen/engine/ tests/`

## Notes For Execution

- Keep generated bindings untouched unless regeneration is explicitly required.
- Prefer small focused commits after each task.
- Treat `kilasifen.engine.de.bindings.*` as internal implementation detail when designing new APIs.
- Preserve backward compatibility where cheap; document breaks clearly where not.
- Do not add more abstraction than needed for the first stable facade.
- Keep low-level imports working during the first stabilization cycle.

Plan complete and saved to `docs/superpowers/plans/2026-04-22-engine-fork-foundation.md`. Ready to execute.
