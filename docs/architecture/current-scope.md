# KilaSifen: alcance actual

KilaSifen es una API fiscal externa, independiente y reutilizable. Tiene dominio,
base, Redis, workers, versiones y despliegues propios. Teko será el primer
consumidor; otros ERP pueden incorporarse sin compartir identidad ni secretos.

## Incluido en v1

- consumidores, credenciales hasheadas, scopes y ownership de emisores;
- factura, nota de crédito y nota de débito mediante contratos tipados;
- cancelación e inutilización tipadas y procesadas por worker dedicado;
- numeración fiscal atómica server-side;
- CSC/PFX/password cifrados y nunca serializados al consumidor;
- jobs RQ, idempotencia, XML, KuDE PDF/datos y consultas;
- webhooks HMAC v1, replay durable, reintentos y defensa SSRF;
- outbox transaccional, leases y dispatch idempotente para jobs durables;
- reconciliación automática y explícita sin reenviar un DE ambiguo;
- sandbox determinista, incluidos timeouts y respuestas perdidas;
- PostgreSQL, Redis, readiness real, imagen no-root y migraciones Alembic;
- staging restringido a SIFEN test;
- SDK TypeScript oficial, tipado y publicable desde `sdks/typescript`;
- portal público Fumadocs versionado junto al contrato en `apps/docs`.

## Fuera de alcance actual

- desplegar o contratar servicios sin autorización;
- habilitar SIFEN producción;
- modificar Teko o integrar FacturaSend;
- OAuth/JWT y email;
- DE de exportación/importación;
- Recibo Electrónico de Dinero fiscal hasta que DNIT publique una estructura
  completa y consumible (ver ADR-0002).

OpenAPI, el portal Fumadocs y [docs/INTEGRATION.md](../INTEGRATION.md) documentan
el contrato HTTP vigente. El SDK TypeScript consume ese contrato; no reemplaza
la API HTTP ni acopla al consumidor a un ERP.
Los archivos `docs/progress` y `docs/superpowers` son historia de implementación,
no fuente de verdad operativa.
