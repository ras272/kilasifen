# `@kilasifen/sdk`

Official, dependency-free TypeScript SDK for the KilaSifen headless fiscal API.
It works in Node.js 20+, Bun, Deno and modern server/edge runtimes that expose
the Fetch and Web Crypto APIs.

## Install

```bash
pnpm add @kilasifen/sdk
```

## Create a client

KilaSifen can be hosted or self-hosted, so `baseUrl` is explicit and never
silently points production traffic at another environment.

```ts
import { KilaSifen } from "@kilasifen/sdk";

const kila = new KilaSifen({
  apiKey: process.env.KILASIFEN_API_KEY!,
  baseUrl: process.env.KILASIFEN_BASE_URL!,
});
```

## Emit a factura

```ts
const result = await kila.facturas.create(
  "emitter_123",
  {
    external_id: "venta_987",
    factura: {
      establecimiento: "001",
      punto: "001",
      cliente: {
        ruc: "80069563-1",
        razon_social: "TIPS S.A.",
      },
      items: [
        {
          codigo_interno: "SKU-1",
          descripcion: "Producto",
          cantidad: 1,
          precio_unitario: 100_000,
          tasa: 10,
        },
      ],
    },
  },
  { idempotencyKey: "venta_987" },
);

console.log(result.data.document.id);
console.log(result.data.job.id);
console.log(result.correlationId);
```

Use one stable `idempotencyKey` for each fiscal intent and persist it with your
sale. The SDK sends it as both `Idempotency-Key` and the current API contract's
`idempotency_key`, so retries remain safe across API versions.

### Deterministic sandbox outcomes

Tests can request one of the API's closed sandbox outcomes without manually
constructing headers:

```ts
await kila.facturas.create(
  "emitter_test",
  {
    external_id: "test_rejection_1",
    factura: {
      cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
      items: [{ descripcion: "Prueba", cantidad: 1, precio_unitario: 1_000 }],
    },
  },
  {
    idempotencyKey: "test_rejection_1",
    sandboxOutcome: "rejected",
  },
);
```

`sandboxOutcome` accepts only `approved`, `approved_with_observation` or
`rejected`. The SDK sends `X-Kila-Test-Outcome` only when this option is
present, and the API rejects it outside the test runtime.

## Emit a nota de crédito

```ts
await kila.notasCredito.create(
  "emitter_123",
  {
    external_id: "devolucion_42",
    nota_credito: {
      cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
      documento_asociado: { cdc: "CDC_DE_44_DIGITOS" },
      items: [
        { descripcion: "Devolución", cantidad: 1, precio_unitario: 50_000 },
      ],
    },
  },
  { idempotencyKey: "devolucion_42" },
);
```

## Emit a nota de débito

La nota de débito incrementa el valor de un DTE existente y siempre requiere
un `documento_asociado`.

```ts
await kila.notasDebito.create(
  "emitter_123",
  {
    external_id: "recupero_logistica_77",
    nota_debito: {
      motivo_emision: "recupero_costo",
      cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
      documento_asociado: {
        tipo: "electronico",
        cdc: "CDC_DE_44_DIGITOS",
      },
      items: [
        {
          descripcion: "Recupero de costo logístico",
          cantidad: 1,
          precio_unitario: 45_000,
          tasa: 10,
        },
      ],
    },
  },
  { idempotencyKey: "recupero_logistica_77_v1" },
);
```

## Query state

```ts
const document = await kila.documents.get("emitter_123", "document_123");
const job = await kila.jobs.get("emitter_123", document.data.job!.id);
```

List and filter documents without assembling query strings manually:

```ts
const page = await kila.documents.list("emitter_123", {
  limit: 50,
  internalStatus: "approved",
  externalId: "venta_987",
});

const taxpayer = await kila.queries.ruc("emitter_123", "80069563-1");
```

If transmission ended ambiguously, reconcile the existing CDC without
resubmitting the DE:

```ts
const reconciliation = await kila.documents.reconcile(
  "emitter_123",
  "document_123",
);

console.log(reconciliation.data.document_query.status);
```

Reconciliation is intentionally API-only and never creates another document.
Use it for documents whose state requires reconciliation; validation errors are
returned as normal typed `KilaSifenError` instances.

## Fiscal events

Cancellation and number-range inutilization are typed resources too; no raw
event payload is required.

```ts
await kila.events.cancel("emitter_123", "document_123", {
  motivo: "Datos fiscales incorrectos",
});

await kila.events.inutilize("emitter_123", {
  timbrado: "12345678",
  document_type: "factura",
  establishment: "001",
  point: "001",
  numero_desde: 120,
  numero_hasta: 125,
  motivo: "Rango no utilizado",
});
```

## Configure webhooks

```ts
const endpoint = await kila.webhooks.create("emitter_123", {
  url: "https://erp.example.com/webhooks/kila",
  secret: process.env.KILASIFEN_WEBHOOK_SECRET!,
  event_subscriptions: ["document.approved", "document.rejected"],
  retry_policy: { max_attempts: 5 },
});

await kila.webhooks.update("emitter_123", endpoint.data.webhook_endpoint.id, {
  secret: process.env.KILASIFEN_WEBHOOK_SECRET_NEXT!,
  is_active: true,
});

await kila.webhooks.replay("emitter_123", endpoint.data.webhook_endpoint.id, {
  event_type: "document.approved",
  payload: { document_id: "document_123" },
});
```

All successful calls return `{ data, correlationId, status }`. Keep the
correlation ID in application logs when requesting support.

## Typed errors

```ts
import { isKilaSifenError } from "@kilasifen/sdk";

try {
  await kila.documents.get("emitter_123", "missing");
} catch (error) {
  if (isKilaSifenError(error)) {
    console.error(error.code, error.category, error.correlationId);
    if (error.retryable) {
      // Retry GET requests. Reuse the same idempotency key for POST requests.
    }
  }
  throw error;
}
```

`KilaSifenError` represents a valid API error envelope, including request
validation failures (`422 request.validation_failed`, with the offending fields
in `details.errors`). `KilaSifenConnectionError` represents timeouts, network
failures, malformed success bodies (`sdk.invalid_response`) and HTTP errors
that arrive without the envelope (`sdk.http_error`, for example an HTML `502`
from a proxy). `sdk.http_error` keeps `status` and the `X-Correlation-ID`
header, and is retryable for `408`, `425`, `429` and `5xx`, like
`KilaSifenError`. Both expose a `retryable` flag, but your retry policy must
still use the same idempotency key for fiscal mutations.

## Verify webhooks

Always verify the exact raw request body **before** parsing JSON. Persist the
delivery ID atomically with your business transaction; the replay callback must
query that durable store, not process memory.

```ts
import { verifyWebhook } from "@kilasifen/sdk";

const verification = await verifyWebhook({
  rawBody,
  secret: process.env.KILASIFEN_WEBHOOK_SECRET!,
  headers: request.headers,
  isDeliveryProcessed: async (deliveryId) => {
    return database.webhookDelivery.exists(deliveryId);
  },
});

if (!verification.valid) {
  throw new Error(`Invalid webhook: ${verification.reason}`);
}

const event = JSON.parse(rawBody);
```

The verifier checks signature version, timestamp tolerance (five minutes by
default), the `v1` HMAC-SHA256 signature and optional replay state using the
same byte-level format as the KilaSifen backend.

## Development

```bash
pnpm install
pnpm lint
pnpm test
pnpm build
```

The package has no runtime dependencies and publishes ESM, CommonJS and
TypeScript declarations.
