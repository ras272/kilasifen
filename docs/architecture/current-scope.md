# KilaSifen: alcance actual

KilaSifen es una API fiscal externa, independiente y reutilizable. Tiene dominio,
base, Redis, workers, versiones y despliegues propios. Teko será el primer
consumidor; otros ERP pueden incorporarse sin compartir identidad ni secretos.

## Incluido en v1

- consumidores, credenciales hasheadas, scopes y ownership de emisores;
- factura y nota de crédito mediante contratos tipados;
- cancelación e inutilización tipadas;
- numeración fiscal atómica server-side;
- CSC/PFX/password cifrados y nunca serializados al consumidor;
- jobs RQ, idempotencia, XML, KuDE PDF/datos y consultas;
- webhooks HMAC v1, replay durable, reintentos y defensa SSRF;
- PostgreSQL, Redis, readiness real, imagen no-root y migraciones Alembic;
- staging restringido a SIFEN test.

## Fuera de alcance actual

- desplegar o contratar servicios sin autorización;
- habilitar SIFEN producción;
- modificar Teko o integrar FacturaSend;
- OAuth/JWT, email, SDK público o portal público;
- DE de exportación/importación y recibos.

OpenAPI y [docs/INTEGRATION.md](../INTEGRATION.md) son el contrato HTTP vigente.
Los archivos `docs/progress` y `docs/superpowers` son historia de implementación,
no fuente de verdad operativa.
