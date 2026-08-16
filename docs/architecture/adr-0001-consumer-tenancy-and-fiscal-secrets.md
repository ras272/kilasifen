# ADR 0001: Consumer tenancy and fiscal-secret boundaries

Status: accepted — 2026-08-16

## Decision

KilaSifen models an API consumer independently from fiscal emitters. A consumer may
own several emitters through `consumer_emitters`; an emitter has at most one owner.
API credentials belong to a consumer, contain explicit scopes, and are stored only
as salted PBKDF2-SHA256 hashes. Authentication returns a non-secret principal with
the credential ID, consumer ID, scopes, and owned emitter IDs.

Tenant routes require both a scope and emitter ownership. An unauthorized emitter
ID is returned as not found to avoid cross-tenant discovery. Global listings and
the server-rendered console require `platform:admin`. Bootstrap keys supplied by
configuration are persisted as hashes before they are accepted and receive only
the explicit platform-administrator identity.

CSC values remain plaintext only in short-lived domain objects. The SQL repository
encrypts them with Fernet before persistence and decrypts them only for fiscal/KuDE
processing. API responses expose `csc_configured` and `csc_id`, never the CSC.
Migration `20260816_06` refuses to migrate existing plaintext CSC values unless
`KILA_SIFEN_ENCRYPTION_KEY` is available.

The deployment setting `KILA_SIFEN_SIFEN_ENVIRONMENT` is authoritative. Emitter
creation/update and all concrete SIFEN gateways reject environment mismatches.
Staging is restricted to test; production also requires
`KILA_SIFEN_ENVIRONMENT=production` and `KILA_SIFEN_ENABLE_PRODUCTION=true`.

## Key rotation

For API credentials, create a second hashed credential for the same consumer and
scopes, deploy it to the caller, verify traffic, then mark the old row inactive.
Never log or persist the newly generated raw value after its one-time handoff.

For CSC or certificates, write the replacement through the scoped secret endpoint,
validate it in SIFEN test, activate it, and retire the old material. For the Fernet
master key, stop writers, back up the database, decrypt each encrypted CSC/PFX value
with the old key, immediately re-encrypt with the new key, atomically update the
records, deploy the new key to API and workers, and verify reads before deleting the
old key. Mixing old/new keys during rolling writes is not supported.

## Tradeoffs

Loading owned emitter IDs into the principal keeps route checks deterministic and
small for the initial product. Consumers with very large emitter fleets may later
move to scoped repository queries without changing the ownership schema. Fernet is
an application-managed envelope suitable for the first independent deployment;
the storage adapter can later move to KMS without changing domain contracts.
