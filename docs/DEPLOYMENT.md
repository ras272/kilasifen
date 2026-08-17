# Railway staging runbook

Este runbook prepara un staging independiente de KilaSifen. No autoriza ni
ejecuta un despliegue, no crea servicios pagos y no habilita SIFEN producción.

## Topología

Un mismo commit/Dockerfile produce dos procesos no-root:

- API: `uvicorn kilasifen.api.app:create_app --factory --host 0.0.0.0 --port $PORT`;
- worker: `rq worker documents events webhooks -u $KILA_SIFEN_REDIS_URL`;
- PostgreSQL es la fuente durable;
- Redis contiene colas, reintentos y leases de rate/concurrency;
- `alembic upgrade head` se ejecuta una sola vez como pre-deploy de la API.

La API expone `/v1/health` (liveness) y `/v1/ready` (PostgreSQL, Redis y workers).
Railway debe usar `/v1/ready` como healthcheck de staging.

## Variables obligatorias

Cargar las mismas variables de runtime en API y worker. Usar referencias privadas
de Railway para PostgreSQL/Redis; no copiar valores al repositorio.

| Variable | Valor de staging |
| --- | --- |
| `KILA_SIFEN_ENVIRONMENT` | `staging` |
| `KILA_SIFEN_SIFEN_ENVIRONMENT` | `test` |
| `KILA_SIFEN_ENABLE_PRODUCTION` | `false` |
| `KILA_SIFEN_DATABASE_URL` | URL privada `postgresql+psycopg://...` de PostgreSQL |
| `KILA_SIFEN_REDIS_URL` | referencia privada del servicio Redis |
| `KILA_SIFEN_API_KEYS` | JSON array con una clave bootstrap admin aleatoria |
| `KILA_SIFEN_ENCRYPTION_KEY` | Fernet 32 bytes base64url; igual en API/worker/migración |
| `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` | `true` |
| `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` | `true` |
| `KILA_SIFEN_REQUEST_LIMITS_ENABLED` | `true` |
| `KILA_SIFEN_RATE_LIMIT_REQUESTS` | `120` inicialmente |
| `KILA_SIFEN_RATE_LIMIT_WINDOW_SECONDS` | `60` |
| `KILA_SIFEN_MAX_CONCURRENT_REQUESTS` | `8` |
| `KILA_SIFEN_REQUEST_LEASE_SECONDS` | `120` |
| `KILA_SIFEN_MAX_PFX_UPLOAD_BYTES` | `2097152` |
| `KILA_SIFEN_LOG_LEVEL` | `INFO` |

`KILA_SIFEN_SENTRY_*` es opcional. No compartir ninguna variable, base, Redis,
certificado, CSC o API key entre staging y una futura producción.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Preparación en Railway (después de autorización)

1. Crear un proyecto de staging y agregar PostgreSQL y Redis.
2. Crear el servicio API desde este repositorio/Dockerfile y fijar las variables.
3. Configurar pre-deploy de API: `alembic upgrade head`.
4. Configurar start command de API con el comando Uvicorn indicado arriba.
5. Configurar healthcheck `/v1/ready`.
6. Desplegar API y verificar health/migración. Readiness puede indicar worker ausente.
7. Crear el servicio worker desde el mismo commit/imagen y configurar su comando RQ.
8. Verificar que readiness observe workers para `documents`, `events` y `webhooks`.
9. Crear consumidor/credencial Teko con `/v1/admin/consumers`; guardar la clave
   entregada una sola vez en el secret store del backend Teko.
10. Cargar sólo material fiscal de pruebas y ejecutar un smoke test autorizado.

En despliegues posteriores: desplegar primero API con pre-deploy/migración,
verificar readiness y después worker al mismo commit. No ejecutar Alembic
simultáneamente desde API y worker.

## Red, timeouts y apagado

- Exponer públicamente sólo API HTTPS. PostgreSQL y Redis usan red privada.
- El worker necesita egress a SIFEN test y webhooks públicos HTTPS.
- Aplicar firewall/proxy de egress que deniegue redes privadas, loopback,
  link-local y metadata cloud. La validación SSRF de aplicación no lo reemplaza.
- Uvicorn usa `exec` y `SIGTERM`; Compose concede 30 s a API y 60 s a worker.
- Empezar con un worker; escalar sólo después de medir cuotas SIFEN y backlog.

## Rollback

1. Conservar backup/snapshot de PostgreSQL antes de migraciones.
2. Si el esquema sigue compatible, redeploy del último commit exitoso de ambos procesos.
3. Preferir roll-forward. Usar `alembic downgrade` sólo si esa revisión fue probada.
4. No restaurar una imagen antigua incapaz de leer el esquema actual.
5. Verificar readiness, colas RQ y una consulta read-only después del rollback.

Rotación: [key-rotation.md](operations/key-rotation.md). Contrato ERP:
[INTEGRATION.md](INTEGRATION.md). Webhooks: [webhooks.md](integrations/webhooks.md).

Referencias Railway: [Docker Compose](https://docs.railway.com/guides/docker-compose),
[pre-deploy](https://docs.railway.com/deployments/pre-deploy-command),
[healthchecks](https://docs.railway.com/deployments/healthchecks),
[variables](https://docs.railway.com/variables/reference) y
[rollback/redeploy](https://docs.railway.com/deployments/deployment-actions).
