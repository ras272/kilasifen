# Kila SIFEN Platform Architecture

## Scope

`pysifen` is the fiscal engine.
`kilasifen` is the platform layer for API, persistence, jobs, and operations.

This separation keeps XML/signature transport logic reusable while exposing one
stable HTTP contract to independent ERP consumers.

Current deployment/integration stance:

- Teko is the first planned consumer, not part of this repository
- consumers own one or more emitters through explicit grants
- strict cross-consumer and cross-emitter isolation is required

For the current MVP scope, treat `docs/architecture/current-scope.md` as the
source of truth.

## Runtime components

- API service (FastAPI)
- background worker (`rq worker`)
- PostgreSQL (source of truth)
- Redis (queue transport)

## Layering

Each business flow follows:

- `router -> service -> repository`

Rules:

- routers only parse/serialize HTTP contracts
- services enforce use cases and domain invariants
- repositories isolate persistence details
- infrastructure adapters bridge to SIFEN transport and cryptography

## Main bounded areas

- Emitters
- Certificates
- Stampings
- Documents and Jobs
- Queries
- Events
- Webhooks
- Consumer access administration
- Admin console (operational read model)

## Data and traceability

Platform persistence stores:

- fiscal payload snapshots
- XML artifacts (`generated_xml`, `signed_xml`, request/response traces)
- normalized status/result fields
- async job lifecycle
- webhook delivery attempts

This makes operations auditable and replayable without parsing raw SOAP at runtime.

## Security boundaries

- API keys stored as salted PBKDF2 hashes with scopes and ownership
- CSC, `.p12`, and passwords encrypted at rest with a mandatory Fernet key
- webhook signing with versioned HMAC over timestamp, delivery, event, and body
- Redis-backed per-credential/emitter rate and concurrency leases
- secrets and endpoints configured through env variables
- emitter data must never leak across tenant/emitter boundaries

## Async strategy

- documents and webhooks run through queued jobs
- SIFEN async behavior is normalized with `kilasifen.domain.common.sifen_async`
- API stays request/response while operational state converges asynchronously

