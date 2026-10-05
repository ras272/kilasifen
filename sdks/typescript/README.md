# `@kilasifen/sdk`

SDK oficial en TypeScript para la API fiscal headless de KilaSifen, sin
dependencias de runtime. Requiere Node.js 20 o superior (`engines` del
paquete).

## Instalación

Todavía no está publicado en npm. Compilalo desde el repositorio e instalalo
desde la carpeta:

```bash
cd sdks/typescript
pnpm install
pnpm build
# en tu proyecto:
pnpm add file:../kilasifen/sdks/typescript
```

## Crear el cliente

KilaSifen se puede usar hospedado o en tu propia infraestructura, así que
`baseUrl` es explícito y nunca apunta a otro ambiente por defecto. Es el origen
de la API, sin `/v1`: el SDK lo agrega en cada ruta (con `/v1` al final las
rutas quedan `/v1/v1/...` y responden `404 request.route_not_found`).

```ts
import { KilaSifen } from "@kilasifen/sdk";

const kila = new KilaSifen({
  apiKey: process.env.KILASIFEN_API_KEY!,
  baseUrl: "https://api.example.com",
});
```

Usalo sólo en el backend del ERP: la API key no puede llegar a un navegador ni
a una app cliente.

## Antes de emitir

- El emisor necesita su perfil fiscal completo (`PATCH /v1/emitters/{emitter_id}`
  con `fiscal_profile`); sin él, crear un documento responde
  `422 emitters.fiscal_profile_required`.
- Para que el worker firme y transmita, el emisor necesita un certificado activo
  y un timbrado activo en la fecha de emisión.
- Emisores, certificados y timbrados todavía no tienen método en el SDK: usá la
  API HTTP (ver la referencia del portal).

## Emitir una factura

```ts
const result = await kila.facturas.create(
  "emitter_123",
  {
    external_id: "venta_987",
    factura: {
      cliente: {
        ruc: "88899990-9",
        razon_social: "CLIENTE FICTICIO SA",
        tipo_contribuyente: 2,
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

console.log(result.status); // 201, o 200 si es un reintento de la misma intención
console.log(result.data.document.id);
console.log(result.data.job.id);
console.log(result.correlationId);
```

- Un cliente con RUC lleva `tipo_contribuyente` (1 persona física, 2 persona
  jurídica), sin valor por defecto, y el DV del RUC se valida.
- Sin `fecha_emision` el documento toma la hora en que se arma el XML. Si la
  enviás, tiene que estar entre 720 h antes y 120 h después del pedido; si no,
  la respuesta es `422 documents.fecha_emision.too_old` o `too_far_ahead`.
- `codigo_seguridad` es opcional: si lo omitís, la plataforma genera uno
  aleatorio y lo conserva en todos los reintentos.
- `redondeo` vale `ninguno` por defecto; `multiplo_50` lleva el total hacia
  abajo a un múltiplo de 50 Gs, sólo en PYG.
- `result.data.document.fiscal_warnings` trae avisos que no impiden la emisión,
  por ejemplo `documents.transmission.emission_far_from_now`.

Usá una `idempotencyKey` estable por intención fiscal y guardala con la venta.
El SDK la manda en el body como `idempotency_key`, que es lo que la API usa;
también envía el header `Idempotency-Key`, que la API hoy ignora.

### Resultados determinísticos del sandbox

En un despliegue con `KILA_SIFEN_ENVIRONMENT=test` podés forzar el resultado
del SIFEN sin armar headers a mano:

```ts
await kila.facturas.create(
  "emitter_test",
  {
    external_id: "prueba_rechazo_1",
    factura: {
      cliente: {
        ruc: "88899990-9",
        razon_social: "CLIENTE FICTICIO SA",
        tipo_contribuyente: 2,
      },
      items: [{ descripcion: "Prueba", cantidad: 1, precio_unitario: 1_000 }],
    },
  },
  {
    idempotencyKey: "prueba_rechazo_1",
    sandboxOutcome: "rejected",
  },
);
```

`sandboxOutcome` acepta los cinco resultados del contrato: `approved`,
`approved_with_observation`, `rejected`, `transport_timeout` y
`accepted_but_response_lost`. Los dos últimos simulan un resultado incierto
para probar la reconciliación. El SDK envía `X-Kila-Test-Outcome` sólo con
esta opción y rechaza ese header si lo agregás a mano; fuera del runtime de
test la API responde `422 sandbox.test_runtime_required`.

## Emitir una nota de crédito

```ts
await kila.notasCredito.create(
  "emitter_123",
  {
    external_id: "devolucion_42",
    nota_credito: {
      motivo_emision: "devolucion",
      cliente: {
        ruc: "88899990-9",
        razon_social: "CLIENTE FICTICIO SA",
        tipo_contribuyente: 2,
      },
      documento_asociado: {
        tipo: "electronico",
        cdc: "01444444017001001000004222026091513640529810",
      },
      items: [
        { descripcion: "Devolución", cantidad: 1, precio_unitario: 50_000 },
      ],
    },
  },
  { idempotencyKey: "devolucion_42" },
);
```

`motivo_emision` es el iMotEmi del MT v150 (E401): `devolucion_y_ajuste`,
`devolucion`, `descuento`, `bonificacion`, `credito_incobrable`,
`recupero_costo`, `recupero_gasto` o `ajuste_precio` (o su código, de 1 a 8).
Enviá siempre el motivo real: si lo omitís, hoy la plataforma informa 1. El
`cdc` del ejemplo es ficticio; usá el CDC de 44 dígitos del DTE que ajustás.

## Emitir una nota de débito

La nota de débito incrementa el valor de un DTE existente y siempre requiere
un `documento_asociado`.

```ts
await kila.notasDebito.create(
  "emitter_123",
  {
    external_id: "recupero_logistica_77",
    nota_debito: {
      motivo_emision: "recupero_costo",
      cliente: {
        ruc: "88899990-9",
        razon_social: "CLIENTE FICTICIO SA",
        tipo_contribuyente: 2,
      },
      documento_asociado: {
        tipo: "electronico",
        cdc: "01444444017001001000004222026091513640529810",
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

## Consultar el estado

```ts
const document = await kila.documents.get("emitter_123", "document_123");
const job = await kila.jobs.get("emitter_123", document.data.job!.id);
```

Listar y filtrar documentos sin armar el query string:

```ts
const page = await kila.documents.list("emitter_123", {
  limit: 50,
  internalStatus: "approved",
  externalId: "venta_987",
});

const taxpayer = await kila.queries.ruc("emitter_123", "88899990-9");
```

La consulta de RUC exige un certificado activo del emisor
(`409 certificates.active_required` si no lo tiene).

Si la transmisión terminó de forma incierta, reconciliá el CDC existente:

```ts
const reconciliation = await kila.documents.reconcile(
  "emitter_123",
  "document_123",
);

console.log(reconciliation.data.document_query.status);
```

`reconcile` consulta el CDC en el SIFEN y no transmite el DE. Si el SIFEN
responde `0420` y el documento estaba pendiente sin un envío en curso, vuelve a
la cola y el worker reenvía el mismo DE firmado (mismo CDC); nunca crea otro
documento.

## Eventos fiscales

La cancelación y la inutilización de un rango también son recursos tipados;
no hace falta armar un payload raw.

```ts
await kila.events.cancel("emitter_123", "document_123", {
  motivo: "Datos fiscales incorrectos",
});

const inutilization = await kila.events.inutilize("emitter_123", {
  timbrado: "12345678",
  document_type: "factura",
  establishment: "001",
  point: "001",
  numero_desde: 120,
  numero_hasta: 125,
  motivo: "Rango no utilizado",
});

console.log(inutilization.data.warnings); // por ejemplo ["inutilization.extemporaneous"]
```

## Configurar webhooks

```ts
const endpoint = await kila.webhooks.create("emitter_123", {
  url: "https://erp.example.com/webhooks/kila",
  secret: process.env.KILASIFEN_WEBHOOK_SECRET!,
  event_subscriptions: ["document.*"],
  retry_policy: { max_attempts: 5 },
});

await kila.webhooks.update("emitter_123", endpoint.data.webhook_endpoint.id, {
  secret: process.env.KILASIFEN_WEBHOOK_SECRET_NEXT!,
  is_active: true,
});

// Evento sintético `webhook.test`, firmado, para probar alcance y firma.
await kila.webhooks.sendTestEvent("emitter_123", endpoint.data.webhook_endpoint.id);

// Reenviar un evento que KilaSifen ya generó para este emisor.
await kila.webhooks.replay("emitter_123", endpoint.data.webhook_endpoint.id, {
  delivery_id: "delivery_123",
});
```

`event_subscriptions` se compara por igualdad o por prefijo con `.*`.
`document.*` recibe todos los cambios de estado, incluidos
`document.approved_with_observation` (un DTE aprobado) y `document.cancelled`;
una lista como `["document.approved", "document.rejected"]` no los recibe. Un
tipo mal escrito no se rechaza: simplemente nunca recibe entregas.

El replay nunca acepta un tipo de evento ni un payload: copia el evento
guardado de una entrega existente (mismo `type`, `data` y `occurred_at`) con un
delivery ID nuevo. Ignorá o confirmá `webhook.test` en tu handler; nunca trae
un cambio de estado fiscal.

Toda llamada exitosa devuelve `{ data, correlationId, status }`. Guardá el
correlation ID en los logs de la aplicación para pedir soporte.

## Errores tipados

```ts
import { KilaSifenConnectionError, isKilaSifenError } from "@kilasifen/sdk";

try {
  await kila.documents.get("emitter_123", "missing");
} catch (error) {
  if (isKilaSifenError(error) || error instanceof KilaSifenConnectionError) {
    console.error(error.code, error.status, error.correlationId);
    if (error.retryable) {
      // Reintentar con backoff. En una creación, con la misma idempotencyKey.
    }
  }
  throw error;
}
```

`KilaSifenError` representa un envelope de error válido de la API, incluidos
los errores de validación (`422 request.validation_failed`, con los campos en
`details.errors`). Cuando una entrada incumple una regla fiscal, trae además el
`code` de la regla (tipo `ValidationErrorItem`):

```ts
import type { ValidationErrorDetails } from "@kilasifen/sdk";

if (isKilaSifenError(error) && error.code === "request.validation_failed") {
  const { errors } = error.details as unknown as ValidationErrorDetails;
  const rules = errors.flatMap((item) => (item.code ? [item.code] : []));
  // por ejemplo ["documents.cliente.tipo_contribuyente_required"]
}
```

`KilaSifenConnectionError` representa timeouts (`sdk.timeout`), errores de red
(`sdk.connection_error`), bodies exitosos ilegibles (`sdk.invalid_response`) y
errores HTTP que llegan sin envelope (`sdk.http_error`, por ejemplo un `502`
HTML de un proxy). `sdk.http_error` conserva `status` y el header
`X-Correlation-ID`, y es reintentable para `408`, `425`, `429` y `5xx`, igual
que `KilaSifenError`. Las dos clases exponen `retryable`, pero tu política de
reintentos tiene que usar la misma clave de idempotencia en las mutaciones
fiscales.

## Verificar webhooks

Verificá siempre el body crudo exacto **antes** de parsear el JSON. Guardá el
delivery ID en la misma transacción que tu operación de negocio; el callback de
replay tiene que consultar ese almacenamiento durable, no la memoria del
proceso.

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
  throw new Error(`Webhook inválido: ${verification.reason}`);
}

const event = JSON.parse(rawBody);
```

El verificador controla la versión de la firma, la tolerancia del timestamp
(cinco minutos por defecto), la firma HMAC-SHA256 `v1` y, si lo pasás, el
estado de replay, con el mismo formato de bytes que el backend de KilaSifen.

## Desarrollo

```bash
pnpm install
pnpm lint
pnpm test
pnpm build
```

El paquete no tiene dependencias de runtime y publica ESM, CommonJS y
declaraciones de TypeScript.
