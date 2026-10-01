# Stack local con Docker Compose

Compose es una facilidad de desarrollo, no la receta de producción.

1. Copiar `.env.example` a `.env`.
2. Generar `POSTGRES_PASSWORD`, `KILA_SIFEN_ENCRYPTION_KEY` y una API key local.
3. Completar `KILA_SIFEN_DATABASE_URL` con el host Compose `postgres`.
4. Dejar en `true` `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` y
   `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` (ver abajo).
5. Ejecutar `docker compose config --quiet` y `docker compose up -d --build`.
6. Consultar `http://127.0.0.1:8000/v1/health` y `/v1/ready`.

## Procesos

| Servicio | Comando | Healthcheck |
| --- | --- | --- |
| `postgres` | imagen oficial | `pg_isready` |
| `redis` | `redis-server --appendonly yes --appendfsync everysec` | `redis-cli ping` |
| `migrate` | `alembic upgrade head` (una vez y termina) | deshabilitado |
| `api` | Uvicorn en el puerto 8000 | el `HEALTHCHECK` de la imagen (`GET /v1/health`) |
| `worker` | `rq worker documents events webhooks` | deshabilitado |
| `outbox` | `python -m kilasifen.infrastructure.jobs.outbox_worker` | deshabilitado |

PostgreSQL, Redis y API se publican sólo en loopback. `migrate` termina antes de
que arranquen API, worker y outbox. Los cuatro usan la misma imagen bloqueada y
no instalan dependencias al iniciar.

El `HEALTHCHECK` del `Dockerfile` consulta HTTP `/v1/health`. Sólo la API sirve
HTTP, así que Compose lo deshabilita en `worker`, `outbox` y `migrate`; sin eso
Docker los marcaría `unhealthy` aunque funcionen bien.

El worker consume las colas y el outbox las alimenta: pasa a RQ los jobs
confirmados en PostgreSQL y vuelve a encolar los reintentos programados. Sin el
outbox ningún documento, evento ni webhook llega al worker.

```bash
docker compose ps
docker compose logs -f api worker outbox migrate
```

## Interruptores de emisión

En el código `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` y
`KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` valen `false` por defecto. `.env.example`
los deja en `true` y Compose pasa el mismo `.env` a todos los procesos.

- `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` lo lee la API. En `false` (o sin
  `KILA_SIFEN_ENCRYPTION_KEY`), `POST` de un documento guarda el documento y su
  job en `queued`, pero no los pasa al outbox: nunca se emiten.
- `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` lo lee el worker. En `false`, los
  cambios de estado de los documentos no publican webhooks.

## Readiness

En `development` y `test`, `/v1/ready` sólo exige PostgreSQL y Redis (`workers`
aparece como `not_required`). En `staging` y `production` exige además workers
en `documents`, `events` y `webhooks` y el heartbeat del outbox
(`kilasifen:outbox:heartbeat`, renovado cada segundo con TTL de 10 s).

## Datos

PostgreSQL usa el volumen `kila-postgres-data` y Redis el volumen
`kila-redis-data` con AOF, así que los jobs encolados, los leases y el heartbeat
sobreviven a un reinicio de contenedor. `docker compose down` conserva ambos
volúmenes. `docker compose down -v` los destruye y se reserva a datos locales
descartables.

## Windows sin contenedores

El worker por defecto de RQ usa `fork` y señales Unix para los timeouts, que no
existen en Windows. Con PostgreSQL y Redis accesibles, levantar cada proceso en
su propia terminal:

```bash
python -m rq.cli worker documents events webhooks \
  -u redis://127.0.0.1:6379/0 \
  --worker-class kilasifen.infrastructure.jobs.worker_classes.CrossPlatformSimpleWorker
python -m kilasifen.infrastructure.jobs.outbox_worker
```
