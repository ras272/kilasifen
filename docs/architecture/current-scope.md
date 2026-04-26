# Kila SIFEN Current Scope

## Source of truth

This file is the current source of truth for what `Kila SIFEN` is and is not.

If another document disagrees with this one, update the other document or mark
it as historical context.

## What Kila SIFEN is

`Kila SIFEN` is an internal FastAPI platform used by the author's ERP.

It is:

- one API integration surface for the ERP
- multi-emitter under the hood
- backed by PostgreSQL, Redis, workers, and persisted XML artifacts
- built on top of `pysifen`, which remains the fiscal engine

The author is the only API integrator today, but each ERP tenant maps to a
different SIFEN emitter with its own RUC, certificate, timbrado, CSC, and
document data. Because of that, strict cross-emitter isolation is in scope.

## What is in the MVP

- Factura Electronica (type 1) typed builder
- Nota de Credito Electronica (type 5) typed builder
- Typed events for cancelation and inutilization
- Server-side atomic numbering by emitter + establishment + point + document type
- Signed XML storage and retrieval
- KuDE PDF endpoint
- KuDE JSON data endpoint for ERP-side branded rendering
- Multi-emitter scoping in code and tests
- Operational endpoints needed to run and debug the platform

## What is out of scope

- Public SDK distribution
- Public docs site / Stripe-style docs
- Public sandbox / status page
- OAuth2 / JWT
- Email delivery
- White-label KuDE rendering inside `kilasifen`
- Recibo as a SIFEN DE type
- Exportacion / Importacion documents

## Deployment and integration model

- Integration model: the ERP consumes the HTTP API
- Deployment model: internal platform run by the author for his ERP
- Tenancy model: one platform instance can host multiple emitters safely

`Kila SIFEN` is not being treated as a public developer platform right now,
and it is not a single-emitter toy service either.

## Canonical docs

Use these documents first:

- `docs/architecture/current-scope.md`
- `docs/architecture/kila-platform.md`
- `docs/architecture/kila-api-contract.md`
- `docs/operations/deployment-compose.md`
- `docs/progress/kila-sifen-v1/`

Treat planning/spec files under `docs/superpowers/` as historical implementation
context unless they were explicitly updated after this file.
