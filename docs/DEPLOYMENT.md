# Deployment guide — Kila SIFEN to production

Cómo llevar Kila SIFEN de desarrollo a un ambiente productivo, ejecutando documentos electrónicos reales contra SIFEN producción (`sifen.set.gov.py`).

## Resumen ejecutivo

| Pregunta | Respuesta |
|---|---|
| ¿Dónde hostear? | Railway / Render (simple) o Hetzner + Coolify (más control, más barato) |
| ¿Encriptación? | Dos capas: at-rest del provider + Fernet a nivel app para cert/CSC |
| Costo inicial | $20–30/mes (managed) o ~€15/mes (self-hosted Hetzner) |
| Tiempo a primer deploy | 1–2 días de trabajo focalizado |
| Cambios de código necesarios | Cero — solo configuración e infraestructura |

---

## Arquitectura mínima de producción

```
                      ┌──────────────────────┐
   Tu ERP ────────────▶  HTTPS (proxy/CDN)   │
   (FastAPI cliente)  └──────────┬───────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
        ┌─────────▼──────────┐       ┌──────────▼─────────┐
        │  API Service       │       │  Worker Service    │
        │  (gunicorn +       │       │  (rq worker)       │
        │   uvicorn workers) │       │  N processes       │
        └─────┬──────┬───────┘       └────┬────────┬──────┘
              │      │                    │        │
              │      └────────┬───────────┘        │
              ▼               ▼                    ▼
        ┌──────────┐    ┌──────────┐         ┌────────────┐
        │ Postgres │    │  Redis   │         │ Sentry SaaS│
        │ managed  │    │ managed  │         │  (errores) │
        │ + backup │    └──────────┘         └────────────┘
        └──────────┘                              
                                                  
                              ┌──────────────────────┐
        Workers ─────────────▶│  SIFEN Web Services  │
                              │  sifen.set.gov.py    │
                              └──────────────────────┘
```

5 piezas: API + Worker + Postgres + Redis + Sentry. Eso es todo.

---

## Opciones de hosting

### Opción A — Railway (recomendada para empezar)

Más simple, cero ops. GitHub → deploy automático. Primer deploy en 30 min.

| Servicio | Plan | Costo aprox |
|---|---|---|
| API service (1 instancia) | Hobby | ~$5/mes |
| Worker service (1 instancia) | Hobby | ~$5/mes |
| Postgres | Hobby | ~$5/mes (1 GB) |
| Redis | Hobby | ~$5/mes |
| **Total** | | **~$20/mes** |

Contras:
- Encarece rápido al escalar
- Región US East por default (~150 ms latencia a SIFEN PY)

**Cuándo usar**: querés deployar hoy y validar end-to-end.

### Opción B — Render

Equivalente a Railway, con la ventaja de tener región **São Paulo** (latencia ~30–50 ms a SIFEN). Costo similar.

**Cuándo usar**: querés mejor latencia desde el día 1.

### Opción C — Hetzner Cloud + Coolify (mejor relación calidad/precio)

VPS Hetzner CCX13 (2 vCPU, 8 GB RAM): **€13/mes**. Coolify (PaaS open source self-hosted) te queda como Railway, pero en tu propia VPS.

| Concepto | Costo |
|---|---|
| VPS Hetzner CCX13 | €13/mes |
| Backups automáticos (snapshots) | €1.30/mes |
| Sentry (free tier) | $0 |
| **Total** | **~€15/mes (~$16)** |

Contras:
- Configurar VPS toma 1–2 horas
- Sos responsable de backups y patches
- Si cae el VPS, downtime hasta restaurar

**Cuándo usar**: tenés algo de manejo Linux, querés ahorrar a largo plazo, volumen inicial bajo.

### Opción D — Fly.io (San Pablo región `gru`)

Buena alternativa CLI-first con región LATAM. Postgres managed via Fly o Neon. Costo similar a Render.

### Recomendación

- **Deployar HOY**: Railway o Render
- **4–6 h libres + ahorro a largo plazo**: Hetzner + Coolify
- **No vayas a AWS/GCP** todavía: overkill, complejidad, costos imprevisibles

---

## Encriptación — qué tenés y qué falta

### Capa 1: At-rest del provider (transparente)

Toda DB managed encripta el disco at-rest por default (AES-256). Railway, Render, Supabase, Neon, Fly Postgres lo hacen sin que toques nada. **Solo elegí un provider serio.**

Si vas Hetzner self-hosted, podés confiar en el cifrado del disco del proveedor.

### Capa 2: Application-level (ya implementado)

Estos campos se guardan **encriptados con Fernet (AES-128 + HMAC)** antes de llegar a Postgres:

- `Certificate.encrypted_p12` (binario del .pfx)
- `Certificate.encrypted_password` (password del .pfx)
- `Emitter.csc` (Código de Seguridad del Cliente)

La clave maestra vive en `KILA_SIFEN_ENCRYPTION_KEY` (env var). **Si la perdés, los certs son irrecuperables.** Tratala como cualquier secreto crítico (password manager, secrets manager).

```bash
# Generar la clave UNA vez (guardarla en password manager)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → algo como: hF9k2Lp...x7Yw3=
```

### Capa 3: TLS in-transit

Todos los providers dan HTTPS automático con Let's Encrypt. **Cero config.**

### Capa 4: Backups encriptados

- Railway / Render / Supabase / Neon: backups diarios automáticos.
- Hetzner self-hosted: configurar `pg_dump` cron a S3-compatible (Cloudflare R2 o Backblaze B2) con cifrado at-rest.

---

## Pre-deploy checklist

### Housekeeping crítico

- [ ] Sacar `tests/test_cert.pfx` del repo (es cert real). Reemplazar por uno autofirmado para tests:
      ```bash
      openssl req -new -newkey rsa:2048 -days 365 -nodes -x509 \
        -keyout test.key -out test.crt -subj "/C=PY/O=Test"
      openssl pkcs12 -export -out tests/test_cert.pfx \
        -inkey test.key -in test.crt -password pass:test1234
      ```
- [ ] Borrar archivos `tmp_*.xml` del root (laboratorio antiguo)
- [ ] Generar `KILA_SIFEN_ENCRYPTION_KEY` y guardar en password manager
- [ ] Crear cuenta Sentry (free tier alcanza) y guardar el DSN

### Infraestructura

- [ ] Dockerfile de producción (no usar `docker-compose.yml` de dev — tiene bind mount)
- [ ] Decidir hosting provider
- [ ] Crear Postgres + Redis en el provider
- [ ] Comprar dominio (~$10/año en Namecheap o Cloudflare Registrar)

### Código

- [ ] Confirmar variables de entorno requeridas (ver sección abajo)
- [ ] Asegurar que `alembic upgrade head` corra en cada deploy
- [ ] Definir Procfile o startup commands para API + worker

### SIFEN producción del primer tenant

- [ ] Cert P12 de **producción** del tenant (distinto del de test)
- [ ] CSC + IdCSC de **producción** del tenant (bajado de e-Kuatia panel producción)
- [ ] Timbrado activo en **producción** del tenant

---

## Dockerfile de producción

Mínimo viable. Ponerlo en raíz como `Dockerfile`:

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir -e ".[transmissao,sign,sentry]"

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends libxml2 libxslt1.1 libpq5 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

RUN useradd -m kila && chown -R kila /app
USER kila

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Default = API. Worker overridea CMD.
CMD ["sh", "-c", "alembic upgrade head && gunicorn kilasifen.api.app:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000"]
```

**Worker service** usa la misma imagen, distinto CMD:

```
rq worker --url $KILA_SIFEN_REDIS_URL kilasifen
```

En Railway / Render configurás dos services apuntando al mismo repo: uno usa el CMD default, el otro lo overridea.

---

## Variables de entorno

```bash
# Base obligatorias
KILA_SIFEN_DATABASE_URL=postgresql://user:pass@host:5432/kilasifen
KILA_SIFEN_REDIS_URL=redis://host:6379/0
KILA_SIFEN_ENCRYPTION_KEY=<la-fernet-key-generada-una-vez>
KILA_SIFEN_API_KEYS=<lista-comma-separated-de-api-keys-validas>

# Sentry (opcional pero recomendado en producción)
KILA_SIFEN_SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
KILA_SIFEN_SENTRY_ENVIRONMENT=production
KILA_SIFEN_RELEASE=v1.0.0
KILA_SIFEN_SENTRY_TRACES_SAMPLE_RATE=0.05
```

> Algunos providers (Railway, Render, Fly) exponen Postgres como `DATABASE_URL` automáticamente. Mapealo a `KILA_SIFEN_DATABASE_URL` en la UI.

---

## Plan de ejecución concreto (1–2 días)

### Día 1 — Preparar repo

1. **Mover cert + housekeeping** (1 h)
   - Borrar `tests/test_cert.pfx` del working tree, agregarlo a `.gitignore`
   - Generar cert autofirmado nuevo para tests CI
   - Limpiar historial con `git filter-repo` si te preocupa exposición pasada
2. **Dockerfile + smoke build local** (1 h)
   - Crear el Dockerfile arriba
   - `docker build -t kilasifen .`
   - Probar `docker run` apuntando a tu Postgres local
3. **Variables de entorno listadas en `.env.example`** (30 min)
   - Documentar el rol de cada una

### Día 2 — Deploy

4. **Crear cuenta + servicios en provider** (1 h)
5. **Conectar repo GitHub** + configurar build/deploy hooks (30 min)
6. **Setear env vars en el panel del provider** (30 min)
7. **Primer deploy + verificar logs** (30 min)
8. **Smoke test contra el deploy** (1 h):
   - Crear emisor de prueba via API pública
   - Subir cert
   - Emitir factura SIFEN test → verificar aprobación
9. **Configurar dominio + HTTPS** (30 min)
10. **Documentar runbook básico** (1 h):
    - Cómo desplegar
    - Cómo hacer rollback
    - Cómo conectarse a la DB para queries de soporte
    - Dónde están los logs

**Total**: ~9 horas focalizadas, repartidas en 1–2 días.

---

## Lo que NO hace falta todavía

- Kubernetes / orquestación compleja
- Multi-región, replicas read-only
- CDN para la API (no tiene assets estáticos)
- Vault para secrets (env vars del provider alcanzan)
- Service mesh, gRPC, etc.
- Auto-scaling agresivo (1 API + 1 worker te alcanza para los primeros 5–10 tenants)

Cuando crezcas a 50+ tenants y tráfico real, ahí escalás piezas individuales. **No optimices para escala que no tenés.**

---

## Camino recomendado

1. **Esta noche o mañana**: Railway → primer deploy → smoke test SIFEN test
2. **Primer tenant pagando real**: migrar a Render São Paulo o Hetzner
3. **10+ tenants**: ahí evaluás si necesitás escalar piezas o aguantás con 1 API + 1 worker

---

## Operación post-deploy (runbook básico)

### Deploy nueva versión

Push a `main` → CI corre tests → si pasa, provider despliega automático. Antes:

1. Correr suite local contra Postgres local: `pytest -q`
2. Verificar que migraciones suben limpio: `alembic upgrade head`

### Rollback

- **Railway / Render / Fly**: hay botón "Redeploy previous version" en la UI
- **Hetzner self-hosted**: revert commit y push, Coolify redeploys automático

### Acceder a la DB en prod (queries de soporte)

```bash
# Provider managed
psql $KILA_SIFEN_DATABASE_URL

# Hetzner self-hosted
ssh root@vps "docker exec -it postgres psql -U kila kilasifen"
```

### Ver logs

- **Railway**: panel de logs por service
- **Render**: panel de logs por service
- **Hetzner + Coolify**: panel de Coolify o `docker logs <container>`
- Logs son JSON estructurados con `correlation_id` para correlacionar request HTTP con job de worker

### Onboardear nuevo tenant en producción

1. Generar API key específica para el tenant si querés trazabilidad por cliente (opcional)
2. Tu ERP llama `POST /v1/emitters` con datos fiscales del tenant
3. Tu ERP sube cert P12 + activa
4. Tu ERP carga timbrado + activa
5. Tu ERP registra webhook
6. Verificar `/v1/emitters/{id}/health` → todo verde
7. Smoke test de una factura real
