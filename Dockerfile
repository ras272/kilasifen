FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.12.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md MIT-LICENSE ./
COPY kilasifen ./kilasifen

RUN uv sync --frozen --no-dev --extra platform --extra transmissao

FROM python:3.12.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

RUN groupadd --system --gid 10001 kilasifen \
    && useradd --system --uid 10001 --gid kilasifen --home-dir /app kilasifen

WORKDIR /app
COPY --from=builder --chown=kilasifen:kilasifen /app/.venv /app/.venv
COPY --chown=kilasifen:kilasifen kilasifen ./kilasifen
COPY --chown=kilasifen:kilasifen alembic ./alembic
COPY --chown=kilasifen:kilasifen alembic.ini pyproject.toml README.md MIT-LICENSE ./

USER kilasifen

EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/v1/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn kilasifen.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
