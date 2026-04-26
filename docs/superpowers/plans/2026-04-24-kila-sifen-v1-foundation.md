# Kila SIFEN V1 Foundation Implementation Plan

> Historical implementation plan: keep for build history only.
> The current source of truth is `docs/architecture/current-scope.md`.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents are available in the current session) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-shaped version of `Kila SIFEN` as a self-hosted, multi-emitter, async-first fiscal platform on top of the existing `pysifen` engine, with HTTP API as the official contract and enough operational surface to power the author's ERP.

**Architecture:** Keep `pysifen` as the fiscal engine and add a new modular-monolith platform layer above it. The platform should follow `router -> service -> repository` boundaries, persist the full fiscal lifecycle, and run as one deployable application with API, workers, and admin console backed by PostgreSQL and Redis.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Redis, RQ, Jinja2/HTMX for admin console, pytest, httpx, ruff

---

## File Map

### New files to create

- `kilasifen/__init__.py`
- `kilasifen/config.py`
- `kilasifen/logging.py`
- `kilasifen/security.py`
- `kilasifen/api/app.py`
- `kilasifen/api/deps.py`
- `kilasifen/api/errors.py`
- `kilasifen/api/schemas/common.py`
- `kilasifen/api/schemas/emitters.py`
- `kilasifen/api/schemas/certificates.py`
- `kilasifen/api/schemas/stampings.py`
- `kilasifen/api/schemas/documents.py`
- `kilasifen/api/schemas/jobs.py`
- `kilasifen/api/schemas/queries.py`
- `kilasifen/api/schemas/events.py`
- `kilasifen/api/schemas/webhooks.py`
- `kilasifen/api/routers/health.py`
- `kilasifen/api/routers/emitters.py`
- `kilasifen/api/routers/certificates.py`
- `kilasifen/api/routers/stampings.py`
- `kilasifen/api/routers/documents.py`
- `kilasifen/api/routers/jobs.py`
- `kilasifen/api/routers/queries.py`
- `kilasifen/api/routers/events.py`
- `kilasifen/api/routers/webhooks.py`
- `kilasifen/application/emitters/service.py`
- `kilasifen/application/certificates/service.py`
- `kilasifen/application/stampings/service.py`
- `kilasifen/application/documents/service.py`
- `kilasifen/application/jobs/service.py`
- `kilasifen/application/queries/service.py`
- `kilasifen/application/events/service.py`
- `kilasifen/application/webhooks/service.py`
- `kilasifen/domain/emitters/models.py`
- `kilasifen/domain/certificates/models.py`
- `kilasifen/domain/stampings/models.py`
- `kilasifen/domain/documents/models.py`
- `kilasifen/domain/jobs/models.py`
- `kilasifen/domain/events/models.py`
- `kilasifen/domain/webhooks/models.py`
- `kilasifen/domain/common/errors.py`
- `kilasifen/domain/common/types.py`
- `kilasifen/repositories/emitters.py`
- `kilasifen/repositories/certificates.py`
- `kilasifen/repositories/stampings.py`
- `kilasifen/repositories/documents.py`
- `kilasifen/repositories/jobs.py`
- `kilasifen/repositories/events.py`
- `kilasifen/repositories/webhooks.py`
- `kilasifen/infrastructure/db/base.py`
- `kilasifen/infrastructure/db/models.py`
- `kilasifen/infrastructure/db/session.py`
- `kilasifen/infrastructure/db/repositories/emitters.py`
- `kilasifen/infrastructure/db/repositories/certificates.py`
- `kilasifen/infrastructure/db/repositories/stampings.py`
- `kilasifen/infrastructure/db/repositories/documents.py`
- `kilasifen/infrastructure/db/repositories/jobs.py`
- `kilasifen/infrastructure/db/repositories/events.py`
- `kilasifen/infrastructure/db/repositories/webhooks.py`
- `kilasifen/infrastructure/crypto/certificate_store.py`
- `kilasifen/infrastructure/jobs/queue.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `kilasifen/infrastructure/sifen/engine.py`
- `kilasifen/infrastructure/sifen/mapper.py`
- `kilasifen/infrastructure/webhooks/deliverer.py`
- `kilasifen/admin/templates/base.html`
- `kilasifen/admin/templates/emitters/list.html`
- `kilasifen/admin/templates/emitter_detail.html`
- `kilasifen/admin/templates/documents/list.html`
- `kilasifen/admin/templates/jobs/list.html`
- `kilasifen/admin/templates/webhooks/list.html`
- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/20260424_01_create_kilasifen_core.py`
- `docker-compose.yml`
- `.env.example`
- `docs/architecture/kila-platform.md`
- `docs/architecture/kila-api-contract.md`
- `docs/operations/deployment-compose.md`
- `docs/operations/job-lifecycle.md`
- `docs/examples/kila_api_emit_document.py`
- `docs/examples/kila_api_register_certificate.py`
- `tests/api/test_health.py`
- `tests/api/test_api_keys.py`
- `tests/api/test_emitters_api.py`
- `tests/api/test_certificates_api.py`
- `tests/api/test_stampings_api.py`
- `tests/api/test_documents_api.py`
- `tests/api/test_jobs_api.py`
- `tests/api/test_queries_api.py`
- `tests/api/test_events_api.py`
- `tests/api/test_webhooks_api.py`
- `tests/application/test_emission_flow.py`
- `tests/application/test_certificate_activation.py`
- `tests/application/test_document_idempotency.py`
- `tests/application/test_webhook_delivery.py`
- `tests/infrastructure/test_certificate_store.py`
- `tests/infrastructure/test_rq_queue.py`
- `tests/conftest.py`

### Existing files to modify

- `pyproject.toml`
- `README.md`
- `.github/workflows/tests.yml`
- `pysifen/sdk/client.py`
- `pysifen/sdk/errors.py`
- `pysifen/sdk/fiscal.py`
- `pysifen/sdk/signer.py`
- `docs/architecture/public-api.md`

### Existing assets to preserve and reuse

- `pysifen/` as the fiscal engine and protocol adapter base
- `docs/examples/send_ares_factura_test.py` as real SIFEN TEST evidence
- current `tests/test_*` coverage around XML generation, signing, and transport

---

## Guiding Decisions

- `pysifen` remains the engine for XML generation, signing, and SIFEN transport.
- The new platform lives in a separate `kilasifen/` package to avoid mixing app concerns into the engine.
- API contracts must be business-oriented and should not mirror raw SOAP envelopes.
- All write operations with fiscal impact must support idempotency and persist full traces.
- The first admin console should optimize for operational usefulness, not visual complexity.
- Every vertical slice must ship with tests or reproducible evidence before the commit.

---

## Chunk 1: Platform Skeleton And Runtime Contracts

### Task 1: Create the platform package and app bootstrap

**Files:**
- Create: `kilasifen/__init__.py`
- Create: `kilasifen/config.py`
- Create: `kilasifen/logging.py`
- Create: `kilasifen/api/app.py`
- Create: `kilasifen/api/routers/health.py`
- Create: `tests/api/test_health.py`
- Modify: `pyproject.toml`

- [ ] Step 1: Add failing tests that boot the FastAPI app and verify `/health` and `/ready`.
- [ ] Step 2: Introduce environment-driven settings with explicit support for PostgreSQL, Redis, encryption key, and SIFEN environment selection.
- [ ] Step 3: Build the minimal FastAPI application factory and register versioned routing under `/v1`.
- [ ] Step 4: Ensure structured logging is initialized centrally and does not leak secrets from config.
- [ ] Step 5: Run `pytest tests/api/test_health.py -v`.
- [ ] Step 6: Commit with message `feat: bootstrap kilasifen platform app`.

### Task 2: Define common API envelope and API key auth

**Files:**
- Create: `kilasifen/security.py`
- Create: `kilasifen/api/deps.py`
- Create: `kilasifen/api/errors.py`
- Create: `kilasifen/api/schemas/common.py`
- Create: `tests/api/test_api_keys.py`
- Modify: `kilasifen/api/app.py`

- [ ] Step 1: Write failing tests for missing API key, invalid API key, and successful authenticated access.
- [ ] Step 2: Define the standard success and error envelopes, including `code`, `message`, `category`, and `correlation_id`.
- [ ] Step 3: Add API key extraction and validation dependencies designed so per-emitter scoping can be layered in cleanly.
- [ ] Step 4: Register global exception handlers that map domain/application errors into the normalized API shape.
- [ ] Step 5: Run `pytest tests/api/test_api_keys.py tests/api/test_health.py -v`.
- [ ] Step 6: Document the response contract in `docs/architecture/kila-api-contract.md`.
- [ ] Step 7: Commit with message `feat: add api key auth and response envelopes`.

---

## Chunk 2: Persistence Foundation And Core Domain Boundaries

### Task 3: Establish database base, session management, and first migration

**Files:**
- Create: `kilasifen/infrastructure/db/base.py`
- Create: `kilasifen/infrastructure/db/session.py`
- Create: `kilasifen/infrastructure/db/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/20260424_01_create_kilasifen_core.py`
- Modify: `pyproject.toml`

- [ ] Step 1: Add database setup tests or smoke checks that validate metadata import and session creation.
- [ ] Step 2: Wire SQLAlchemy 2 session management with clear transaction boundaries for request and worker usage.
- [ ] Step 3: Create the initial migration for emitters, certificates, stampings, documents, jobs, webhooks, and API keys.
- [ ] Step 4: Keep the schema minimal but aligned with the approved canonical domain.
- [ ] Step 5: Run `pytest tests/api/test_health.py -v` and a local Alembic upgrade smoke check.
- [ ] Step 6: Commit with message `feat: add database foundation and initial schema`.

### Task 4: Create repositories and domain models for emitters, certificates, and stampings

**Files:**
- Create: `kilasifen/domain/emitters/models.py`
- Create: `kilasifen/domain/certificates/models.py`
- Create: `kilasifen/domain/stampings/models.py`
- Create: `kilasifen/domain/common/errors.py`
- Create: `kilasifen/domain/common/types.py`
- Create: `kilasifen/repositories/emitters.py`
- Create: `kilasifen/repositories/certificates.py`
- Create: `kilasifen/repositories/stampings.py`
- Create: `kilasifen/infrastructure/db/repositories/emitters.py`
- Create: `kilasifen/infrastructure/db/repositories/certificates.py`
- Create: `kilasifen/infrastructure/db/repositories/stampings.py`
- Create: `tests/application/test_certificate_activation.py`

- [ ] Step 1: Write failing tests for active-certificate uniqueness and active-timbrado selection per emitter.
- [ ] Step 2: Model the first domain invariants outside the API layer.
- [ ] Step 3: Implement repository interfaces and SQLAlchemy-backed implementations with business-oriented methods.
- [ ] Step 4: Keep repository contracts free of raw HTTP or SIFEN-specific concerns.
- [ ] Step 5: Run `pytest tests/application/test_certificate_activation.py -v`.
- [ ] Step 6: Commit with message `feat: add core emitter certificate and stamping domain`.

---

## Chunk 3: Emitter, Certificate, And Timbrado Management

### Task 5: Ship emitter management API and service layer

**Files:**
- Create: `kilasifen/application/emitters/service.py`
- Create: `kilasifen/api/schemas/emitters.py`
- Create: `kilasifen/api/routers/emitters.py`
- Create: `tests/api/test_emitters_api.py`

- [ ] Step 1: Write failing API tests for create, update, get, and deactivate emitter flows.
- [ ] Step 2: Implement `router -> service -> repository` flow with strict Pydantic validation.
- [ ] Step 3: Enforce uniqueness rules around external ids and RUC/DV combinations.
- [ ] Step 4: Return stable resource shapes with timestamps and operational status.
- [ ] Step 5: Run `pytest tests/api/test_emitters_api.py -v`.
- [ ] Step 6: Commit with message `feat: add emitter management api`.

### Task 6: Add encrypted certificate ingestion and activation

**Files:**
- Create: `kilasifen/application/certificates/service.py`
- Create: `kilasifen/infrastructure/crypto/certificate_store.py`
- Create: `kilasifen/api/schemas/certificates.py`
- Create: `kilasifen/api/routers/certificates.py`
- Create: `tests/api/test_certificates_api.py`
- Create: `tests/infrastructure/test_certificate_store.py`

- [ ] Step 1: Write failing tests for certificate upload, metadata extraction, activation, and read redaction.
- [ ] Step 2: Implement encrypted storage for `.p12` blobs and passwords using a dedicated storage service.
- [ ] Step 3: Reuse the current `pysifen` signing/certificate parsing path where practical instead of duplicating certificate logic.
- [ ] Step 4: Expose only non-sensitive metadata in read APIs, including fingerprint and expiration.
- [ ] Step 5: Run `pytest tests/api/test_certificates_api.py tests/infrastructure/test_certificate_store.py -v`.
- [ ] Step 6: Commit with message `feat: add encrypted certificate management`.

### Task 7: Add timbrado management API

**Files:**
- Create: `kilasifen/application/stampings/service.py`
- Create: `kilasifen/api/schemas/stampings.py`
- Create: `kilasifen/api/routers/stampings.py`
- Create: `tests/api/test_stampings_api.py`

- [ ] Step 1: Write failing tests for create, activate, list, and invalid-date timbrado flows.
- [ ] Step 2: Implement service validation for date windows and one-active-timbrado semantics per emitter where applicable.
- [ ] Step 3: Make the response contract future-safe for establishment/point-of-issuance rules.
- [ ] Step 4: Run `pytest tests/api/test_stampings_api.py -v`.
- [ ] Step 5: Commit with message `feat: add stamping management api`.

---

## Chunk 4: Document Lifecycle And Emission Jobs

### Task 8: Model documents and jobs with idempotent creation

**Files:**
- Create: `kilasifen/domain/documents/models.py`
- Create: `kilasifen/domain/jobs/models.py`
- Create: `kilasifen/repositories/documents.py`
- Create: `kilasifen/repositories/jobs.py`
- Create: `kilasifen/infrastructure/db/repositories/documents.py`
- Create: `kilasifen/infrastructure/db/repositories/jobs.py`
- Create: `kilasifen/application/documents/service.py`
- Create: `kilasifen/application/jobs/service.py`
- Create: `kilasifen/api/schemas/documents.py`
- Create: `kilasifen/api/schemas/jobs.py`
- Create: `kilasifen/api/routers/documents.py`
- Create: `kilasifen/api/routers/jobs.py`
- Create: `tests/application/test_document_idempotency.py`
- Create: `tests/api/test_documents_api.py`
- Create: `tests/api/test_jobs_api.py`

- [ ] Step 1: Write failing tests for document creation with `external_id` and `idempotency_key`.
- [ ] Step 2: Define the initial document and job state machines in the domain layer.
- [ ] Step 3: Persist payload snapshots, status transitions, and job links as first-class records.
- [ ] Step 4: Expose document creation and job inspection endpoints without yet calling real SIFEN.
- [ ] Step 5: Run `pytest tests/application/test_document_idempotency.py tests/api/test_documents_api.py tests/api/test_jobs_api.py -v`.
- [ ] Step 6: Commit with message `feat: add document and job lifecycle foundation`.

### Task 9: Add queue wiring and worker execution path

**Files:**
- Create: `kilasifen/infrastructure/jobs/queue.py`
- Create: `kilasifen/infrastructure/jobs/workers.py`
- Create: `tests/infrastructure/test_rq_queue.py`
- Modify: `kilasifen/application/jobs/service.py`

- [ ] Step 1: Write failing tests for queue enqueue behavior and worker payload hydration.
- [ ] Step 2: Add RQ integration with explicit queue names for emission, consultation, events, and webhooks.
- [ ] Step 3: Ensure job correlation ids and retry metadata survive the enqueue/dequeue path.
- [ ] Step 4: Keep worker entrypoints thin and delegate business logic back into application services.
- [ ] Step 5: Run `pytest tests/infrastructure/test_rq_queue.py tests/api/test_jobs_api.py -v`.
- [ ] Step 6: Commit with message `feat: add background queue and worker wiring`.

### Task 10: Connect the emission worker to the `pysifen` engine

**Files:**
- Create: `kilasifen/infrastructure/sifen/engine.py`
- Create: `kilasifen/infrastructure/sifen/mapper.py`
- Create: `tests/application/test_emission_flow.py`
- Modify: `pysifen/sdk/client.py`
- Modify: `pysifen/sdk/errors.py`
- Modify: `pysifen/sdk/fiscal.py`
- Modify: `pysifen/sdk/signer.py`

- [ ] Step 1: Write failing service tests for the end-to-end emission flow using a fake or stub SIFEN adapter.
- [ ] Step 2: Build an infrastructure adapter that turns stored business payloads into the `pysifen` structures needed for XML generation, signing, and transmission.
- [ ] Step 3: Persist generated XML, signed XML, SIFEN request metadata, raw response snapshots, and normalized result fields.
- [ ] Step 4: Mark transport failures, fiscal validation failures, and SIFEN rejections as different error categories.
- [ ] Step 5: Keep any `pysifen` changes narrowly focused on reusable engine concerns that benefit both the SDK and the platform.
- [ ] Step 6: Run `pytest tests/application/test_emission_flow.py -v`.
- [ ] Step 7: Re-run the high-value engine regressions: `pytest tests/test_assinatura.py tests/test_ares_de_test_xml.py tests/test_sdk_client.py -v`.
- [ ] Step 8: Commit with message `feat: process emission jobs through pysifen`.

---

## Chunk 5: Queries, Events, And Source-Of-Truth Expansion

### Task 11: Add read-side SIFEN query workflows

**Files:**
- Create: `kilasifen/application/queries/service.py`
- Create: `kilasifen/api/schemas/queries.py`
- Create: `kilasifen/api/routers/queries.py`
- Create: `tests/api/test_queries_api.py`

- [ ] Step 1: Write failing tests for query-RUC and query-document endpoints.
- [ ] Step 2: Route query operations through the same emitter-scoped infrastructure adapter path.
- [ ] Step 3: Persist request and response traces when the operation has operational value.
- [ ] Step 4: Ensure the API returns normalized business responses instead of raw SOAP payloads.
- [ ] Step 5: Run `pytest tests/api/test_queries_api.py -v`.
- [ ] Step 6: Commit with message `feat: add query workflows`.

### Task 12: Add fiscal event workflows

**Files:**
- Create: `kilasifen/domain/events/models.py`
- Create: `kilasifen/repositories/events.py`
- Create: `kilasifen/infrastructure/db/repositories/events.py`
- Create: `kilasifen/application/events/service.py`
- Create: `kilasifen/api/schemas/events.py`
- Create: `kilasifen/api/routers/events.py`
- Create: `tests/api/test_events_api.py`

- [ ] Step 1: Write failing tests for creating an event over an existing document and tracking its status.
- [ ] Step 2: Reuse the existing engine/event support rather than creating a second event stack.
- [ ] Step 3: Persist event payloads, XML artifacts, job references, and normalized SIFEN outcomes.
- [ ] Step 4: Run `pytest tests/api/test_events_api.py tests/test_eventos.py -v`.
- [ ] Step 5: Commit with message `feat: add fiscal event workflows`.

---

## Chunk 6: Webhooks And Admin Console

### Task 13: Add webhook endpoints, signing, and delivery history

**Files:**
- Create: `kilasifen/domain/webhooks/models.py`
- Create: `kilasifen/repositories/webhooks.py`
- Create: `kilasifen/infrastructure/db/repositories/webhooks.py`
- Create: `kilasifen/infrastructure/webhooks/deliverer.py`
- Create: `kilasifen/application/webhooks/service.py`
- Create: `kilasifen/api/schemas/webhooks.py`
- Create: `kilasifen/api/routers/webhooks.py`
- Create: `tests/api/test_webhooks_api.py`
- Create: `tests/application/test_webhook_delivery.py`

- [ ] Step 1: Write failing tests for endpoint registration, signed delivery, retryable failure handling, and replay.
- [ ] Step 2: Implement signed webhook payloads with a stable event shape and explicit delivery records.
- [ ] Step 3: Schedule webhook dispatch through the background job system rather than from inline API requests.
- [ ] Step 4: Run `pytest tests/api/test_webhooks_api.py tests/application/test_webhook_delivery.py -v`.
- [ ] Step 5: Commit with message `feat: add webhook delivery subsystem`.

### Task 14: Ship the first operational admin console

**Files:**
- Create: `kilasifen/admin/templates/base.html`
- Create: `kilasifen/admin/templates/emitters/list.html`
- Create: `kilasifen/admin/templates/emitter_detail.html`
- Create: `kilasifen/admin/templates/documents/list.html`
- Create: `kilasifen/admin/templates/jobs/list.html`
- Create: `kilasifen/admin/templates/webhooks/list.html`
- Modify: `kilasifen/api/app.py`

- [ ] Step 1: Add thin server-rendered admin routes for the first operational screens.
- [ ] Step 2: Make the console read-heavy first: inspect emitters, certificates, timbrados, documents, jobs, and webhook failures.
- [ ] Step 3: Add a minimal set of operator actions only where they are low-risk and high-value, such as retrying a job or activating a certificate.
- [ ] Step 4: Verify the pages render and the key actions work through API-backed service calls.
- [ ] Step 5: Commit with message `feat: add operational admin console`.

---

## Chunk 7: DX, Packaging, And Deployment Readiness

### Task 15: Document the platform and ship runnable local deployment

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `docs/architecture/kila-platform.md`
- Create: `docs/operations/deployment-compose.md`
- Create: `docs/operations/job-lifecycle.md`
- Create: `docs/examples/kila_api_emit_document.py`
- Create: `docs/examples/kila_api_register_certificate.py`
- Modify: `README.md`
- Modify: `docs/architecture/public-api.md`

- [ ] Step 1: Write deployment docs for API, worker, PostgreSQL, and Redis in Docker Compose.
- [ ] Step 2: Add examples showing how an ERP would register a certificate and create a document through the official API.
- [ ] Step 3: Update the README to explain the relationship between `pysifen` and the new `Kila SIFEN` platform.
- [ ] Step 4: Keep the engine-facing docs and platform-facing docs clearly separated.
- [ ] Step 5: Smoke-test the Compose stack locally.
- [ ] Step 6: Commit with message `docs: add platform deployment and integration guidance`.

### Task 16: Strengthen CI and verification for the new platform

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `pyproject.toml`

- [ ] Step 1: Add platform test execution to CI, split so engine regressions and API/platform tests are both visible.
- [ ] Step 2: Add lint coverage for the new `kilasifen/` package.
- [ ] Step 3: Add migration and app-start smoke checks so packaging failures are caught early.
- [ ] Step 4: Run the local equivalent commands before finalizing the change.
- [ ] Step 5: Commit with message `ci: verify kilasifen platform and engine regressions`.

---

## Suggested Execution Order

1. Chunk 1
2. Chunk 2
3. Chunk 3
4. Chunk 4
5. Chunk 5
6. Chunk 6
7. Chunk 7

Do not start the admin console before the core API, persistence, and jobs exist.
Do not let platform code reach directly into low-level `pysifen` modules from routers.
Do not collapse certificate storage, document persistence, and job state into one service layer blob.

## Verification Commands

- `pytest tests/api/test_health.py -v`
- `pytest tests/api/test_api_keys.py -v`
- `pytest tests/api/test_emitters_api.py tests/api/test_certificates_api.py tests/api/test_stampings_api.py -v`
- `pytest tests/application/test_document_idempotency.py tests/api/test_documents_api.py tests/api/test_jobs_api.py -v`
- `pytest tests/infrastructure/test_rq_queue.py tests/application/test_emission_flow.py -v`
- `pytest tests/api/test_queries_api.py tests/api/test_events_api.py -v`
- `pytest tests/api/test_webhooks_api.py tests/application/test_webhook_delivery.py -v`
- `pytest tests/test_assinatura.py tests/test_ares_de_test_xml.py tests/test_sdk_client.py -v`
- `pytest tests -v --tb=short`
- `ruff check kilasifen/ pysifen/ tests/`

## Notes For Execution

- Treat `pysifen` as the reusable fiscal engine, not as the place to grow platform concerns.
- Prefer additive changes over risky rewrites of existing engine code.
- Keep all secret material behind config or encrypted storage services.
- Preserve the proven SIFEN TEST emission path while layering the platform above it.
- Favor one vertical slice completed end-to-end over broad but half-finished scaffolding.
- Keep commits small and task-scoped, with one finished unit of value per commit.

Plan complete and saved to `docs/superpowers/plans/2026-04-24-kila-sifen-v1-foundation.md`. Review it before starting implementation so the stack and package layout are locked.
