# Deployment Guide (Docker Compose)

## Objective

Run a full local stack for API + workers with PostgreSQL and Redis.

## Files

- `docker-compose.yml`
- `.env.example`

## Quick start

1. Copy `.env.example` to `.env`.
2. Set:
   - `KILA_SIFEN_ENCRYPTION_KEY`
   - `KILA_SIFEN_API_KEYS`
3. Start stack:

```bash
docker compose up -d --build
```

4. Check services:

```bash
docker compose ps
```

## What each service does

- `postgres`: source-of-truth persistence
- `redis`: queue transport
- `api`: runs migrations and exposes HTTP API on `:8000`
- `worker`: processes `documents` and `webhooks` queues

## Health checks

- API:

```bash
curl -H "X-API-Key: local-dev-api-key" http://localhost:8000/v1/health
```

- Ready:

```bash
curl -H "X-API-Key: local-dev-api-key" http://localhost:8000/v1/ready
```

## Logs

```bash
docker compose logs -f api
docker compose logs -f worker
```

## Stop

```bash
docker compose down
```

To remove Postgres data volume:

```bash
docker compose down -v
```

## Operational notes

- API and worker both install project dependencies on startup in this development compose.
- For production, build fixed images and pin dependency versions.
- Keep `KILA_SIFEN_ENCRYPTION_KEY` stable; rotating it requires re-encryption strategy for stored certificate material.

