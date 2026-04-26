# Kila SIFEN API Contract

This document describes the internal HTTP contract used by the author's ERP.
For current product/deployment scope, see `docs/architecture/current-scope.md`.

## Versioning

The platform API is exposed under an explicit version prefix:

- `/v1`

## Success Envelope

Successful responses use a consistent top-level shape:

```json
{
  "data": {
    "status": "ok"
  },
  "correlation_id": "4f1cf5fa-8cf6-4db8-9d1f-64266fe33268"
}
```

Rules:

- `data` contains the business payload
- `correlation_id` identifies the request across API, workers, and logs

## Error Envelope

Structured failures use this shape:

```json
{
  "error": {
    "code": "auth.invalid_api_key",
    "message": "API key is invalid.",
    "category": "authentication",
    "correlation_id": "4f1cf5fa-8cf6-4db8-9d1f-64266fe33268"
  }
}
```

Rules:

- `code` is machine-readable and stable
- `message` is safe to show in logs and dashboards
- `category` groups the failure type
- `correlation_id` must match the request context

## Authentication

V1 uses API keys.

Clients send the key in:

- `X-API-Key`

Protected endpoints reject missing or invalid keys with `401`.
