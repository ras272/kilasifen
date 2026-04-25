# Kila SIFEN Platform Architecture

## Scope

`pysifen` is the fiscal engine.
`kilasifen` is the platform layer for API, persistence, jobs, and operations.

This separation keeps XML/signature transport logic reusable while giving ERP integrations a stable HTTP contract.

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

- API access through API keys (`X-API-Key`)
- `.p12` and passwords encrypted at rest with Fernet key
- webhook signing with HMAC (`X-Kila-Signature`)
- secrets and endpoints configured through env variables

## Async strategy

- documents and webhooks run through queued jobs
- SIFEN async behavior is normalized with `kilasifen.domain.common.sifen_async`
- API stays request/response while operational state converges asynchronously

