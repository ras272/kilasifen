# KilaSifen Docs

Sitio público de integración construido con Next.js y Fumadocs. El contenido
editorial vive en `content/docs`; la referencia HTTP se genera desde el OpenAPI
versionado en `public/openapi.json`.

## Desarrollo local

Desde la raíz del repositorio:

```powershell
uv run python scripts\export_openapi.py
cd apps\docs
pnpm install --frozen-lockfile
pnpm dev
```

Abrir `http://localhost:3000`. Antes de un commit que cambie rutas o schemas de
FastAPI, volver a ejecutar el exportador.

## Validación

```powershell
uv run python scripts\export_openapi.py --check
cd apps\docs
pnpm lint
pnpm typecheck
pnpm build
```

## Vercel

1. Importar el mismo repositorio que contiene la API.
2. Crear un proyecto llamado `kilasifen-docs`.
3. Configurar **Root Directory** como `apps/docs`.
4. Mantener el preset `Next.js`; Vercel detecta `pnpm` desde el lockfile local.
5. Definir `NEXT_PUBLIC_SITE_URL` con la URL pública definitiva.
6. Desplegar y después asociar el subdominio `docs.<dominio>`.
7. Crear en DNS el CNAME exacto mostrado por Vercel.

La documentación no necesita acceso a PostgreSQL, Redis, certificados ni API
keys. Tampoco expone un proxy de requests: los ejemplos están destinados al
backend integrador.
