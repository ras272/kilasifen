# Stack local con Docker Compose

Compose es una facilidad de desarrollo, no la receta de producción.

1. Copiar `.env.example` a `.env`.
2. Generar `POSTGRES_PASSWORD`, `KILA_SIFEN_ENCRYPTION_KEY` y una API key local.
3. Completar `KILA_SIFEN_DATABASE_URL` con el host Compose `postgres`.
4. Ejecutar `docker compose config --quiet` y `docker compose up -d --build`.
5. Consultar `http://127.0.0.1:8000/v1/health` y `/v1/ready`.

PostgreSQL, Redis y API se publican sólo en loopback. `migrate` termina antes de
API/worker. Ambos consumen la misma imagen bloqueada y no instalan dependencias al
iniciar.

```bash
docker compose ps
docker compose logs -f api worker migrate
```

Para Windows sin contenedor:

```bash
python -m rq.cli worker documents webhooks \
  -u redis://127.0.0.1:6379/0 \
  --worker-class kilasifen.infrastructure.jobs.worker_classes.CrossPlatformSimpleWorker
```

`docker compose down` conserva PostgreSQL. `docker compose down -v` destruye el
volumen y se reserva a datos locales descartables.
