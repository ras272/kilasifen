# Kila SIFEN Design

> Historical planning note: this file captures an earlier design direction.
> The current source of truth is `docs/architecture/current-scope.md`.

**Date:** 2026-04-24

## Goal

Design `Kila SIFEN` as a self-hosted, developer-first fiscal platform for Paraguay that is genuinely easier to integrate than the current ecosystem.

The platform must serve two audiences at once:

- external integrators who need a clean, documented, stable API
- the author's ERP, which will consume the same official API in production

The product should feel modern, operationally safe, and practical to adopt in real systems, not just technically correct.

## Product Position

`Kila SIFEN v1` is a hybrid platform:

- an internal fiscal engine that handles XML generation, signing, transmission, validation, and state transitions
- an official HTTP API that all clients use, including the author's ERP
- an admin console for operators

This is not a public multi-tenant SaaS in v1.

It is a `self-hosted` platform intended to run inside one organization's infrastructure, but it must support `multiple emitters/RUCs in the same installation`.

## Core Product Decisions

### Deployment model

- self-hosted
- Docker Compose first
- architecture should be cleanly migratable to Kubernetes later

### Integration model

- HTTP API is the official integration surface
- the author's ERP consumes the same API as any third party
- no separate privileged “internal path” should exist in v1

### Tenant model

- one installation supports multiple emitters
- each emitter is isolated by configuration, credentials, certificates, documents, jobs, logs, and webhooks

### Processing model

- async-first
- synchronous helpers may exist later for narrow cases, but jobs are the main operational model

### Functional scope

`Kila SIFEN v1` is intentionally broad and complete:

- document emission
- document queries
- RUC queries
- fiscal events
- certificate management
- timbrado management
- job tracking
- webhook delivery
- admin console

### Authentication

- API keys only in v1
- designed for backend-to-backend usage

### Persistence stance

`Kila SIFEN` is a `source of truth` for fiscal operations, not a thin proxy.

It must persist:

- normalized input payloads
- generated XML
- signed XML
- request/response to SIFEN
- internal state transitions
- SIFEN result codes and messages
- events
- webhook deliveries
- certificate metadata

## Recommended Architecture

## Top-level shape

Use a `modular monolith`.

This is the best trade-off for v1 because it keeps the operational footprint small while still allowing strong internal separation.

The platform ships as one deployable application with:

- public HTTP API
- admin console backend
- internal workers for async processing
- database
- queue/backing job system
- encrypted storage for sensitive fiscal material

### Why not microservices

Microservices would add too much operational complexity too early:

- more deployment overhead
- more debugging surfaces
- more auth and network boundaries
- slower product iteration

The problem space is already complex because of SIFEN itself. v1 should not add unnecessary distributed-systems complexity.

### Why not SDK-first only

An SDK-only product would undercut the cross-language integration goal and would force the author's ERP and third parties into language/runtime coupling.

The engine still matters, but the official contract should remain HTTP.

## Internal layering

The application should follow explicit internal boundaries:

### 1. API layer

Responsibilities:

- authenticate API keys
- authorize per emitter/account scope
- validate input contracts
- map HTTP requests into use cases
- serialize standardized responses/errors

This layer must not contain fiscal rules or direct SIFEN protocol logic.

### 2. Application layer

Responsibilities:

- define use cases
- orchestrate repositories and domain services
- create jobs
- coordinate side effects

Examples of use cases:

- `CreateEmitter`
- `RegisterCertificate`
- `ActivateCertificate`
- `CreateStamping`
- `CreateDocument`
- `SubmitEmissionJob`
- `ProcessEmissionJob`
- `ConsultRuc`
- `ConsultDocument`
- `CreateEvent`
- `DispatchWebhook`

### 3. Domain / fiscal workflow layer

Responsibilities:

- fiscal invariants
- state transitions
- idempotency rules
- emitter-specific routing decisions
- certificate selection rules
- timbrado applicability
- consistency between payload, XML, signed XML, and SIFEN results

This layer should model fiscal operations clearly and remain testable without HTTP or database concerns.

### 4. Repository layer

Responsibilities:

- persistence interfaces
- document storage/retrieval
- emitter configuration persistence
- job persistence
- webhook delivery persistence
- certificate metadata persistence

The repositories should expose business-oriented methods, not raw SQL-shaped contracts.

### 5. Infrastructure adapters

Responsibilities:

- SIFEN SOAP adapter
- XML signing adapter
- encrypted certificate storage
- database implementations
- job queue implementation
- webhook HTTP delivery
- logging/metrics/tracing hooks

This keeps vendor/tooling choices behind replaceable boundaries.

## Canonical Domain Model

The central concept is not “a request to SIFEN”.

The central concepts are `Emitter`, `FiscalDocument`, and `Job`.

### Instance

Represents one installed Kila SIFEN environment.

Mostly operational metadata, versioning, and global configuration.

### Emitter

Represents one company/RUC operating through the installation.

Fields should include:

- internal id
- external id
- RUC and DV
- legal name
- tax environment
- API-visible status
- default currency rules if needed later
- CSC and IdCSC
- timestamps

An emitter owns:

- certificates
- timbrados
- fiscal documents
- events
- webhooks

### Certificate

Represents a `.p12` uploaded for one emitter.

Kila SIFEN must manage certificates as a first-class feature.

Fields should include:

- internal id
- emitter id
- logical name
- active flag
- fingerprint
- serial number if available
- subject summary
- detected RUC from certificate if extractable
- valid from
- valid until
- upload timestamp
- status

Sensitive material:

- raw `.p12` content encrypted at rest
- password encrypted at rest

Storage strategy:

- v1 starts with internal encrypted storage
- storage backend should be abstracted so future external secret/storage systems can be added without changing the API contract

### Stamping

Represents a timbrado associated with one emitter.

Fields should include:

- internal id
- emitter id
- number
- start date
- end date if applicable
- establishment rules if needed
- point of issuance rules if needed
- active/inactive status

### FiscalDocument

The core persisted business object.

Fields should include:

- internal id
- emitter id
- external id from client
- idempotency key
- document type
- business payload snapshot
- generated XML
- signed XML
- CDC
- current internal status
- current SIFEN status
- SIFEN result code/message
- correlation metadata
- created/updated timestamps

This object must remain the source of truth for the full document lifecycle.

### FiscalEvent

Represents an event issued over a fiscal document.

Fields should include:

- internal id
- emitter id
- target document id
- event type
- input payload
- generated XML
- signed XML if applicable
- status
- SIFEN result metadata

### Job

Represents async work.

All important long-running operations should be job-backed.

Fields should include:

- internal id
- emitter id
- job type
- related entity type/id
- status
- attempts
- error snapshot
- scheduled timestamp
- started timestamp
- finished timestamp
- worker correlation id

Job types should cover:

- emission
- document consultation
- RUC consultation if async becomes useful
- event submission
- webhook delivery
- retries

### WebhookEndpoint

Represents a configured outbound destination.

Fields should include:

- internal id
- emitter id or broader scope if later needed
- URL
- secret/signing material
- event subscriptions
- active flag
- retry policy settings

### WebhookDelivery

Represents each webhook attempt.

Fields should include:

- internal id
- webhook endpoint id
- event type
- payload snapshot
- attempt number
- request timestamp
- response code
- response body snapshot with safe truncation
- final status

## API Design Direction

The public API should be resource-oriented and easy to learn.

It should not simply mirror SIFEN SOAP structures.

### Versioning

- explicit HTTP versioning from day 1
- recommended path format: `/v1/...`

### Primary resources

#### Emitters

Manage emitter registration and fiscal configuration.

Examples:

- create emitter
- update emitter config
- enable/disable emitter
- view emitter state

#### Certificates

Manage uploaded certificates.

Examples:

- upload certificate
- validate certificate metadata
- activate certificate
- list certificate history
- detect expiration risk

#### Stampings

Manage timbrados per emitter.

Examples:

- create timbrado
- activate timbrado
- list valid timbrados

#### Documents

Core developer workflow resource.

Examples:

- create document draft
- submit for emission
- inspect status
- list processing attempts
- retrieve XML artifacts
- retry failed operation

#### Queries

Read-oriented operations against SIFEN.

Examples:

- query RUC
- query DE by CDC/reference

#### Events

Create and track fiscal events associated with existing documents.

#### Jobs

Expose async processing state.

Examples:

- list jobs
- get job detail
- inspect failure reason
- retry job

#### Webhooks

Manage outbound notifications.

Examples:

- create endpoint
- rotate secret
- replay deliveries
- inspect failures

## API DX Principles

### Stable, typed contracts

Input/output schemas should be explicit and documented.

### Idempotency by design

Sensitive write operations should accept `idempotency-key`.

Especially:

- document creation
- emission submission
- event creation
- webhook replay actions if exposed

### ERP correlation

The API should encourage `external_id` or equivalent client reference on business objects.

This is essential for ERP integration and should not be treated as optional ergonomics.

### Predictable error model

Errors should be normalized, with:

- machine-readable code
- human-readable message
- category
- optional field details
- correlation id

### Avoid XML as the primary contract

For most clients, the API should accept structured fiscal payloads and return business-oriented results.

Raw XML should be retrievable when needed, but not required for normal integration.

## Processing and Job Model

The platform is async-first.

### Emission flow

Recommended end-to-end flow:

1. client creates document or submits emission request
2. Kila persists the document payload
3. Kila creates a job
4. worker resolves emitter config, timbrado, certificate, and fiscal rules
5. worker generates XML
6. worker signs XML
7. worker sends to SIFEN
8. worker persists request, response, and normalized status
9. worker updates document and job states
10. worker emits webhooks

### Job status model

Suggested statuses:

- `queued`
- `running`
- `succeeded`
- `failed`
- `retry_scheduled`
- `cancelled`

### Retry philosophy

Retries should be explicit and safe.

Examples:

- transport/network issues: retryable
- malformed fiscal payload: not retryable without change
- invalid certificate/password: not retryable
- webhook temporary failure: retryable

Retries must never hide the original failure context.

## Certificate Management

Certificate management is required in v1.

### Source of certificate operations

The author's ERP will likely be the main actor performing certificate upload and rotation.

That is acceptable, but Kila still must own the certificate lifecycle as a platform concern.

### Required capabilities

- upload `.p12`
- store encrypted blob
- store encrypted password
- validate that the certificate parses correctly
- expose fingerprint and expiration metadata
- associate certificate to one emitter
- mark one certificate active
- prevent ambiguous active selection
- audit who changed certificate state

### Security requirements

- encrypted at rest
- encrypted secrets never returned in read APIs
- operational logs must not leak passwords or raw certificate content
- audit trail for create/activate/deactivate actions

## Source-of-Truth Requirements

Kila SIFEN must preserve complete fiscal traceability.

At minimum it should store:

- input payload received from client
- generated XML
- signed XML
- SIFEN request envelope where relevant
- SIFEN raw response snapshot
- normalized response fields
- state transitions
- retry history
- event history
- webhook history

This gives operators and integrators enough evidence to debug real fiscal issues.

## Webhooks

Webhooks are part of v1.

They should be treated as a serious subsystem, not an afterthought.

### Use cases

- document approved
- document rejected
- job failed
- event processed
- consultation result available
- certificate expiration warning if product later includes it

### Delivery requirements

- signed webhook payloads
- retry support
- delivery history
- replay capability
- per-endpoint event subscriptions
- correlation ids

### Event shape

Webhook payloads should be concise but useful:

- event id
- event type
- emitter id
- resource id
- external id if present
- status snapshot
- timestamp
- URL/reference to fetch full resource detail

## Admin Console

V1 should include an admin console because the platform will need day-to-day operations beyond API usage.

### Minimum views

- emitters
- certificates
- timbrados
- documents
- jobs
- events
- webhooks
- delivery failures

### Primary operator tasks

- inspect emitter status
- upload/activate certificates
- configure timbrados
- inspect document lifecycle
- view XML artifacts
- inspect SIFEN failures
- retry jobs
- replay webhooks

The UI should be operationally focused rather than CRM-like.

## Suggested Runtime Stack

The exact stack can still be changed later, but the design assumes something like:

- FastAPI for HTTP API and admin backend
- PostgreSQL as system of record
- Redis or equivalent for async job coordination
- encrypted blob storage in database or attached object storage
- Docker Compose deployment

This is a recommendation, not a rigid implementation lock.

## Observability and Operations

The platform must be easy to operate in real life.

### Logging

Structured logs with at least:

- emitter id
- document id
- job id
- webhook delivery id
- external id
- correlation id

### Metrics

At minimum:

- jobs by status
- emission success/failure
- webhook success/failure
- processing latency
- SIFEN call latency

### Auditability

Audit important actions:

- certificate upload/activation
- timbrado changes
- document retries
- webhook replays

## Non-Goals for V1

The following should stay out of scope initially:

- public hosted multi-tenant SaaS offering
- user/password auth system
- arbitrary custom workflow builders
- infinite document-type customization layer
- Kubernetes-first deployment
- premature microservice decomposition

## Main Risks

### 1. Turning into a thin SIFEN wrapper

If the API mirrors SOAP too closely, the developer experience will still be poor.

### 2. Mixing fiscal core with HTTP concerns

If application/domain boundaries are weak, the platform will become hard to test and evolve.

### 3. Weak emitter isolation

Multi-emitter support without strict separation will create operational and security failures.

### 4. Underestimating certificate lifecycle

Certificate handling is not a side feature. It is central infrastructure.

### 5. Async model without good observability

Jobs and webhooks without clear traceability become operationally painful very quickly.

## Success Criteria

`Kila SIFEN v1` is successful when:

- a third-party backend can integrate using only the documented HTTP API
- the author's ERP uses the same API without backdoors
- one installation can safely operate multiple emitters
- fiscal operations are traceable end-to-end
- operators can diagnose failures without raw database forensics
- certificate and timbrado management are first-class features
- document processing is reliable and webhook-capable
- the platform is genuinely simpler to integrate than current alternatives

## Recommended First Planning Direction

The first implementation plan should likely split the work into these vertical tracks:

1. platform skeleton and runtime architecture
2. emitter, certificate, and timbrado management
3. document lifecycle and emission jobs
4. consultation and event flows
5. webhooks and admin console
6. docs, examples, and DX hardening

That planning step should happen only after this design is accepted as the written source of truth.
