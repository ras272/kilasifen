# Pysifen Fork Design

**Date:** 2026-04-22

## Goal

Turn the current repo into a production-grade SIFEN SDK and integration platform that is pleasant to use in real projects, robust under load, and credible as an open-source reference for Paraguay.

## Scope Decision

This fork focuses first on the SDK.

The API/gateway is a future track, not part of the first implementation wave. It stays in this document only as long-term direction so the fork does not paint itself into a corner.

## Canonical Identity

The fork needs one explicit identity strategy before implementation starts.

### Decision

- keep distribution name `sifen` in the near term for compatibility
- keep import namespace `pysifen` in the near term to avoid a disruptive package rename
- standardize all new public examples around `pysifen`
- document the split clearly in packaging metadata and README

### Compatibility policy

- existing low-level imports from `pysifen.de.bindings.*` continue to work during the first stabilization cycle
- those imports are treated as low-level and legacy, but not removed immediately
- all new docs and examples should use the stable facade
- any future import-namespace rename must ship with aliases and a documented deprecation window

## Current State Summary

The repository is already a strong schema-first base:

- XSD-backed bindings are generated and tested.
- XML parsing/serialization works reliably for the covered samples.
- Digital signature and SOAP transmission exist.
- The local suite passed during this review with `109 passed, 1 skipped`.

The main gap is not correctness of the foundation, but product quality around it:

- public API is too tied to generated internals
- transmission layer is thin and operationally fragile
- validation is heuristic-based
- performance wins are still on the table
- OSS/community packaging is incomplete

## Recommended Runtime Decision

Stay on Python.

### Why

- The hot path is dominated by XML, crypto, mTLS, and remote SIFEN latency.
- `lxml` and `cryptography` already push key work into optimized native code.
- Measured local smoke performance is already acceptable for a baseline:
  - parse 100 sample XMLs: about `0.70s`
  - serialize 100 sample XMLs: about `0.70s`
  - sign 10 sample XMLs: about `0.70s`
- A rewrite now would create high delivery cost with unclear business payoff.

### Recommended deployment model

- CPython `3.12` or `3.13`
- multiple process workers
- horizontal scale at the API/service layer
- explicit connection reuse, schema caching, and certificate reuse

This is a deployment recommendation, not a new package requirement. The fork can continue to support `>=3.10` while production guidance prefers `3.12+`.

### When to reconsider another language

Only after profiling a production workload and confirming that Python remains the bottleneck after:

- schema cache
- transport/session reuse
- PKCS12/key material reuse
- retry/backoff discipline
- proper batching strategy

If a rewrite is ever justified, Java or Kotlin would be the most natural candidate because of the SOAP/XML enterprise ecosystem.

## Target Product Shape

The fork should become two related deliverables.

### 1. SDK

Purpose: embedded use inside ERP, e-commerce, billing, and internal systems.

Responsibilities:

- create and manipulate DE/event objects
- parse XML into Python objects
- serialize to XML
- validate against the correct schema
- sign documents
- submit and query SIFEN
- expose predictable typed errors and responses

### 2. API/Gateway

Purpose: future central integration service for teams that do not want to work directly with XML, certificates, and SOAP.

Responsibilities:

- receive JSON or canonical payloads
- map them to SDK objects
- sign and submit to SIFEN
- persist request/response history
- expose webhook/job status APIs
- centralize retries, observability, and policy enforcement

The SDK comes first. The API/gateway should be built on top of it later, not implemented in the first fork wave.

## Architectural Direction

### A. Stable public facade

The current public surface is too deep and version-coupled. Consumers should not need imports like `pysifen.de.bindings.v150.fe_v141`.

Target facade examples:

```python
from pysifen import TEST, PRODUCCION, sign_xml
from pysifen.sdk import SifenClient
from pysifen.models import RDe
from pysifen.builders import FacturaBuilder
```

Principles:

- keep generated bindings available, but low-level
- publish a small stable API for common use cases
- keep version-specific internals behind adapters/facades
- preserve current low-level import paths during the transition window

### Migration policy

- phase 1: add the facade without removing existing import paths
- phase 2: document deep generated imports as legacy
- phase 3: only consider deprecation warnings after the facade proves stable

### B. Explicit schema registry

`validate_xml()` must stop guessing by scanning all XSD files in a directory.

Target behavior:

- map root type or binding class to the exact XSD entrypoint
- compile and cache `XMLSchema` objects
- expose deterministic validation errors

### Validation source of truth

The registry must be explicit and checked in, not guessed at runtime.

Minimum first matrix:

- `RDe` or root tag `rDE` -> `FE_v141.xsd`
- event roots -> `Evento_v150.xsd`
- DE reception request/response roots -> matching `siRecep*.xsd`
- consultation request/response roots -> matching `WS_*.xsd`

Required behavior:

- unknown root -> typed configuration error
- schema load failure -> typed internal validation error
- invalid XML -> structured validation error list
- valid XML -> success result compatible with the current API shape

### C. Hardened transport layer

The transport layer should become an explicit subsystem rather than a helper wrapper.

Target capabilities:

- reusable HTTP session/transport
- configurable timeout
- retry policy with backoff
- typed transport and protocol exceptions
- request correlation id
- optional wire logging hooks
- explicit cleanup via context manager

### Lifecycle contract

- one client instance owns one session/transport bundle
- one client instance owns its temporary certificate files if temporary files are still used
- `close()` is idempotent
- context-manager exit always calls `close()`
- requests after `close()` fail predictably with a typed error
- retries must not rebuild certificate state on every attempt

### D. Signature service

Signing should be a reusable service with controlled lifecycle.

Target capabilities:

- decode PKCS12 once per client/session
- reuse key and certificate material
- separate XML preparation from signing
- return typed errors with actionable messages

### E. Builders and ergonomic helpers

Generated dataclasses are powerful but not user-friendly for mainstream adoption.

High-value helpers:

- `FacturaBuilder`
- `NotaCreditoBuilder`
- `NotaDebitoBuilder`
- `NotaRemisionBuilder`
- event builders
- CDC helper
- QR helper
- lot helper

### Helper contracts

CDC helper:

- input: structured DE identity data or a built DE object
- output: canonical 44-digit CDC string
- invalid or incomplete input: typed error

QR helper:

- input: DE object plus any extra values required by the official manual
- output: canonical QR URL string
- the implementation must name the manual section it follows

### F. Version compatibility model

The fork should treat schema versioning as a first-class concern.

Target model:

- versioned internal packages remain in `bindings`
- version-neutral facade for common operations
- clear compatibility matrix in docs
- predictable migration path for future `v200`

## High-Priority Product Gaps

### P0

- identity and compatibility policy
- stable public API
- correct and cached validation
- robust transport/session lifecycle
- typed domain errors
- retry/backoff/timeouts
- documentation for end-to-end flow

### P1

- builders for common DE types
- CDC and QR helpers
- async/polling helper for lot and DTE flows
- structured logging and metrics hooks
- improved sample coverage for all 8 DE types

### P2

- richer builders and helper coverage
- KuDE/PDF generation
- Odoo integration adapters

### Future Track

The following are intentionally out of scope for the first fork plan:

- API/gateway service
- webhook/event processing helpers
- persistence adapters
- platform-level async orchestration

## Important Findings From This Review

### Validation gap

`pysifen.CommonMixin.validate_xml()` currently scans the schema folder and tries each `.xsd` until one validates. During this review, validating the sample `factura_electronica.xml` returned:

`Element '{http://ekuatia.set.gov.py/sifen/xsd}rDE': No matching global declaration available for the validation root.`

That makes validation a real product gap, not just a refactor target.

### Operational gaps

- SOAP client is recreated per use.
- transport/session reuse is minimal
- cleanup relies on `__del__`
- there are no retries or explicit timeout controls
- no observability hooks exist yet

### OSS maturity gaps

- no `CONTRIBUTING.md`
- no `CHANGELOG.md`
- no `SECURITY.md`
- no compatibility policy
- naming is split between `sifen` and `pysifen`

## Proposed Repository Evolution

### Near-term structure

```text
pysifen/
  __init__.py
  sdk/
    __init__.py
    client.py
    errors.py
    validation.py
    signatures.py
  transport/
    __init__.py
    http.py
    soap.py
    retry.py
  builders/
    __init__.py
    factura.py
    nota_credito.py
    nota_debito.py
    nota_remision.py
  helpers/
    __init__.py
    cdc.py
    qr.py
  de/
    bindings/
    schemas/
    samples/
```

The generated bindings stay where they are. The new code forms a product layer above them.

## Non-Goals For The First Fork Wave

- building a hosted multi-tenant platform
- choosing a database or queue architecture
- implementing webhook delivery infrastructure
- redesigning generated bindings
- removing all low-level imports immediately

## Delivery Phases

### Phase 1: Fork foundation

- lock identity and compatibility policy
- define public facade
- add typed errors
- replace validation heuristic
- fix package identity/docs

### Phase 2: Production hardening

- reuse certificate/session/client state
- add retries, backoff, and timeouts
- add logging hooks and metrics points
- support explicit context lifecycle

### Phase 3: Ergonomics

- builders
- CDC/QR helpers
- richer examples
- all 8 DE types represented in samples/tests

### Phase 4: Platform

- HTTP API/gateway
- async job orchestration
- persistence/outbox/status tracking
- webhook/event delivery

Phase 4 should be treated as a separate later initiative, not part of the first execution plan.

## Community Positioning

For the Paraguayan community, the winning strategy is not just "open source library". It is:

- trustworthy
- well-documented
- operationally safe
- easy to adopt without reading the full manual first

That means the fork should optimize for:

- clean onboarding
- examples that work
- stable API promises
- visible maintenance process

## Success Criteria

The fork will be in a strong state when:

- package identity is documented and predictable
- current low-level imports still work while the facade is adopted
- a normal Python developer can send a DE without importing deep generated modules
- validation uses the correct schema deterministically
- transport errors are understandable and retry-safe
- all 8 DE types have examples/tests
- schema/version drift is easy to track
- docs support both SDK consumers and API consumers
- the project can be recommended publicly without caveats about fragility
