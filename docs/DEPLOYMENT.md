# Railway staging runbook

Este runbook prepara un staging independiente de KilaSifen. No autoriza ni
ejecuta un despliegue, no crea servicios pagos y no habilita SIFEN producción.
Cada comportamiento de Railway citado acá está en su documentación oficial
(enlaces al final); revisarla antes de aplicar el runbook por si cambió.

## Topología

Un mismo commit y el mismo `Dockerfile` producen tres servicios Railway, todos
con el usuario no-root de la imagen, más PostgreSQL y Redis gestionados por
Railway:

| Servicio | Proceso | Start command | Pre-deploy | Healthcheck |
| --- | --- | --- | --- | --- |
| `api` | Uvicorn | vacío: usa el `CMD` del `Dockerfile` | `alembic upgrade head` | `/v1/health` |
| `worker` | RQ, colas `documents`, `events` y `webhooks` | `/bin/sh -c "exec rq worker documents events webhooks --url $KILA_SIFEN_REDIS_URL"` | vacío | vacío |
| `outbox` | despachador del outbox | `python -m kilasifen.infrastructure.jobs.outbox_worker` | vacío | vacío |

- PostgreSQL es la fuente durable. Redis guarda colas, leases de
  rate/concurrency y el heartbeat del outbox.
- El outbox es obligatorio. La API y el worker no encolan en RQ: escriben
  filas de outbox en la misma transacción que el job, y este proceso las
  publica en RQ. También publica los reintentos programados cuando vence su
  `scheduled_at`. Sin el outbox nada llega al worker y `/v1/ready` no pasa.
- La migración no es un servicio: corre como pre-deploy de `api`, una sola vez
  por deploy. No configurar Alembic en `worker` ni en `outbox`.
- No importar `docker-compose.yml` en Railway. El importador ignora
  `depends_on`, así que se pierde el orden migración → procesos; Compose queda
  sólo para desarrollo local.

### Start commands

Para servicios construidos desde un `Dockerfile`, Railway ejecuta el start
command en forma *exec*, que no expande variables. Cuando el comando necesita
una variable hay que envolverlo en un shell: `/bin/sh -c "exec ..."`. El
`exec` deja al proceso real como PID 1 para que reciba el `SIGTERM`.

- `api`: dejar el start command vacío. El `CMD` del `Dockerfile` ya es
  `sh -c "exec uvicorn kilasifen.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"`
  y escucha en el `PORT` que inyecta Railway. Si hiciera falta definirlo, usar
  `/bin/sh -c "exec uvicorn kilasifen.api.app:create_app --factory --host 0.0.0.0 --port $PORT"`.
- `worker`: necesita `$KILA_SIFEN_REDIS_URL`, por eso va con `/bin/sh -c`.
  Sin el shell, RQ recibiría como URL el texto literal
  `$KILA_SIFEN_REDIS_URL`.
- `outbox` y el pre-deploy de `api` no usan variables en la línea de comando:
  leen `KILA_SIFEN_*` desde el entorno, así que la forma exec alcanza.

## Health, readiness y healthcheck de Railway

- `/v1/health` es liveness: responde 200 si el proceso atiende y no consulta
  dependencias.
- `/v1/ready` consulta PostgreSQL y Redis. En `staging` y `production` exige
  además workers registrados en `documents`, `events` y `webhooks` y el
  heartbeat del outbox; si falta algo responde 503 (`missing:documents,...` o
  `missing:outbox_dispatcher`).

Ninguno de los dos pasa por el limitador de requests.

El healthcheck del servicio `api` en Railway es **`/v1/health`**, no
`/v1/ready`. Railway sólo consulta el healthcheck al iniciar cada deploy (no
monitorea después), espera un 2xx durante 300 s por defecto y, si no llega,
marca el deploy como fallido. Con `/v1/ready` el primer deploy de `api` falla
siempre: `worker` y `outbox` todavía no existen y no deben arrancar antes de la
migración que corre en ese mismo deploy. En deploys posteriores, una caída del
worker bloquearía además cualquier deploy de la API.

`/v1/ready` se verifica a mano después de cada deploy y desde un monitor
externo, porque Railway no hace monitoreo continuo. Railway hace el
healthcheck desde el host `healthcheck.railway.app` y al `PORT` que inyecta;
KilaSifen no filtra por `Host`, así que no hace falta configurar nada más.

`worker` y `outbox` no sirven HTTP: dejar su healthcheck vacío y no generarles
dominio. Su estado se ve en `/v1/ready`.

## Variables obligatorias

Cargar las mismas variables `KILA_SIFEN_*` en `api`, `worker` y `outbox`. El
pre-deploy corre con las variables de `api`. Conviene definirlas como
variables compartidas del entorno (`${{shared.NOMBRE}}`) para que no diverjan.
No copiar valores al repositorio.

| Variable | Valor de staging |
| --- | --- |
| `KILA_SIFEN_ENVIRONMENT` | `staging` |
| `KILA_SIFEN_SIFEN_ENVIRONMENT` | `test` |
| `KILA_SIFEN_ENABLE_PRODUCTION` | `false` |
| `KILA_SIFEN_DATABASE_URL` | `postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}` |
| `KILA_SIFEN_REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `KILA_SIFEN_API_KEYS` | JSON array con una clave bootstrap admin aleatoria |
| `KILA_SIFEN_ENCRYPTION_KEY` | Fernet 32 bytes base64url, la misma en los tres servicios |
| `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` | `true` (ver abajo) |
| `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` | `true` (ver abajo) |
| `KILA_SIFEN_REQUEST_LIMITS_ENABLED` | `true` |
| `KILA_SIFEN_RATE_LIMIT_REQUESTS` | `120` inicialmente |
| `KILA_SIFEN_RATE_LIMIT_WINDOW_SECONDS` | `60` |
| `KILA_SIFEN_MAX_CONCURRENT_REQUESTS` | `8` |
| `KILA_SIFEN_REQUEST_LEASE_SECONDS` | `120` |
| `KILA_SIFEN_MAX_PFX_UPLOAD_BYTES` | `2097152` |
| `KILA_SIFEN_LOG_LEVEL` | `INFO` |

`Postgres` y `Redis` son los nombres de los servicios de base de datos en el
proyecto; ajustarlos si se llaman distinto. Las variables `PG*` y `REDIS_URL`
de esas plantillas apuntan a la red privada. La URL de PostgreSQL se arma con
`postgresql+psycopg://` porque KilaSifen no reescribe el esquema y el único
driver instalado es psycopg 3.

**Interruptores de emisión.** En el código
`KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` y `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS`
valen `false` y la validación de staging no los exige:

- `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` lo lee `api`. En `false`, un documento
  se guarda con su job en `queued` pero no pasa al outbox y nunca se emite.
- `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` lo lee `worker`. En `false`, los
  cambios de estado de los documentos no publican webhooks.

Variables propias de Railway, por servicio:

| Servicio | Variable | Valor | Motivo |
| --- | --- | --- | --- |
| `api` | `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | `30` | Uvicorn termina las requests en curso tras el `SIGTERM` |
| `worker` | `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | `60` | RQ termina el job en curso (por ejemplo, una llamada al SIFEN) tras el `SIGTERM` |

Railway da por defecto 0 s entre el `SIGTERM` y el `SIGKILL`. Los valores
replican el `stop_grace_period` de Compose. `outbox` no lo necesita: termina
apenas recibe `SIGTERM` y las filas que tenía tomadas se liberan cuando vence
su lease de 30 s.

`KILA_SIFEN_SENTRY_*` es opcional. No compartir ninguna variable, base, Redis,
certificado, CSC o API key entre staging y una futura producción.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Primer despliegue (después de autorización)

1. Crear un proyecto de staging y agregar PostgreSQL y Redis desde las
   plantillas de Railway.
2. Crear el servicio `api` desde este repositorio. Railway usa el
   `Dockerfile` de la raíz. Fijar las variables, dejar el start command vacío,
   configurar el pre-deploy `alembic upgrade head`, el healthcheck `/v1/health`
   y `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30`. Generar el dominio público.
3. Desplegar `api`. El pre-deploy corre en un contenedor aparte con las
   variables del servicio y acceso a la red privada; si falla, el deploy no
   sigue. Verificar `GET /v1/health` → 200. En este punto `GET /v1/ready`
   responde 503 con `workers` en `down`: es lo esperado.
4. Crear el servicio `worker` desde el mismo repositorio y commit, con las
   mismas variables, el start command de la tabla,
   `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=60`, sin pre-deploy, sin healthcheck y
   sin dominio. Desplegarlo.
5. Crear el servicio `outbox` igual, con su start command. Desplegarlo.
6. Verificar `GET /v1/ready` → 200 con `workers` en `ok`. Si dice
   `missing:outbox_dispatcher`, revisar los logs de `outbox`; si nombra colas,
   los de `worker`.
7. Crear consumidor/credencial Teko con `/v1/admin/consumers`; guardar la clave
   entregada una sola vez en el secret store del backend Teko.
8. Cargar sólo material fiscal de pruebas y ejecutar un smoke test autorizado.

## Despliegues posteriores

Railway no ordena los deploys disparados por un push a GitHub: cada servicio
despliega por su cuenta, aunque los tres salgan del mismo repositorio. Para
que la migración corra antes de que `worker` y `outbox` usen el código nuevo:

1. Dejar el autodeploy de GitHub sólo en `api` y deshabilitarlo en `worker` y
   `outbox`. Opcionalmente activar "Wait for CI" en `api`; exige que el
   workflow corra en `push` a la rama desplegada (hoy sólo `main`) y conviene
   activarlo recién cuando el CI pase.
2. Esperar a que el deploy de `api` termine bien: pre-deploy con código 0 y
   healthcheck en 2xx.
3. Desplegar `worker` y `outbox` con "Deploy Latest Commit" y comprobar que
   los tres servicios muestran el mismo commit. Si entró un commit nuevo a la
   rama entretanto, repetir desde el paso 2.
4. Verificar `GET /v1/ready` → 200.

Las migraciones deben ser compatibles con el código anterior
(expand/contract): mientras dura el despliegue conviven la API nueva con el
worker y el outbox del commit anterior. Nunca ejecutar Alembic desde `worker`
u `outbox` ni desde dos servicios a la vez.

## Red, timeouts y apagado

- Exponer públicamente sólo `api` (HTTPS). PostgreSQL y Redis usan la red
  privada (`*.railway.internal`), que existe en runtime y en el pre-deploy pero
  no durante el build.
- `worker` necesita egress a SIFEN test y a los webhooks públicos HTTPS.
- Aplicar firewall/proxy de egress que deniegue redes privadas, loopback,
  link-local y metadata cloud. La validación SSRF de aplicación no lo reemplaza.
- La política de reinicio por defecto de Railway es "On Failure" con hasta 10
  reinicios. Un `worker` u `outbox` caído se ve en `/v1/ready`.
- Empezar con una instancia de `worker` y una de `outbox`; escalar workers sólo
  después de medir cuotas SIFEN y backlog. Varias instancias de `outbox` son
  seguras (toman filas con lease y `SKIP LOCKED`), como pasa brevemente
  durante el solapamiento de un deploy, pero una alcanza.

## Rollback

1. Conservar backup/snapshot de PostgreSQL antes de migraciones.
2. Si el esquema sigue compatible, volver `api`, `worker` y `outbox` al último
   deploy exitoso. El rollback de Railway restaura la imagen y las variables
   del deploy elegido, servicio por servicio.
3. Preferir roll-forward. Usar `alembic downgrade` sólo si esa revisión fue probada.
4. No restaurar una imagen antigua incapaz de leer el esquema actual.
5. Verificar readiness, colas RQ y una consulta read-only después del rollback.

Rotación: [key-rotation.md](operations/key-rotation.md). Contrato ERP:
[INTEGRATION.md](INTEGRATION.md). Webhooks: [webhooks.md](integrations/webhooks.md).
Stack local: [deployment-compose.md](operations/deployment-compose.md).

Referencias Railway:
[start command](https://docs.railway.com/deployments/start-command),
[pre-deploy](https://docs.railway.com/deployments/pre-deploy-command),
[healthchecks](https://docs.railway.com/deployments/healthchecks),
[draining y overlap](https://docs.railway.com/deployments/deployment-teardown)
(default de 0 s en la [referencia de deployments](https://docs.railway.com/deployments/reference)),
[autodeploys y Wait for CI](https://docs.railway.com/deployments/github-autodeploys),
[orden de deploys y rollback](https://docs.railway.com/deployments/deployment-actions),
[política de reinicio](https://docs.railway.com/deployments/restart-policy),
[variables](https://docs.railway.com/variables/reference),
[PostgreSQL](https://docs.railway.com/databases/postgresql),
[Redis](https://docs.railway.com/databases/redis),
[red privada](https://docs.railway.com/networking/private-networking/how-it-works) e
[importación de Docker Compose](https://docs.railway.com/guides/docker-compose).
