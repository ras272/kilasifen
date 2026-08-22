# Contrato KilaSifen v1 para Teko y otros ERP

KilaSifen es independiente. La API key vive sólo en el backend ERP y viaja como
`X-API-Key` sobre HTTPS; nunca llega al navegador. OpenAPI está en
`/openapi.json`; las rutas públicas usan `/v1` y JSON `snake_case`.

## Ownership y scopes

Cada clave pertenece a un consumidor y sólo ve sus emisores. Un ID ajeno responde
`404`. Scopes: `tenant:read`, `tenant:write`, `fiscal:write`, `secrets:write` y el
separado `platform:admin`, que nunca se entrega a un ERP.

El administrador crea consumidor y clave (mostrada una sola vez):

```text
POST /v1/admin/consumers
POST /v1/admin/consumers/{consumer_id}/credentials
```

## Envelope y errores

Éxito: `{"data": {}, "correlation_id": "uuid"}`.

```json
{
  "error": {
    "code": "documents.not_found",
    "message": "Resource was not found.",
    "category": "not_found",
    "correlation_id": "uuid",
    "details": null
  }
}
```

`401` credencial; `403` scope; `404` inexistente/ajeno; `409` conflicto; `422`
payload; `429` límite; `503` dependencia. Conservar `correlation_id`.

## Crear factura

```http
POST /v1/emitters/{emitter_id}/documents/facturas
Content-Type: application/json
X-API-Key: ...
```

```json
{
  "external_id": "teko_invoice_1842",
  "idempotency_key": "teko_invoice_1842_v1",
  "factura": {
    "establecimiento": "001",
    "punto": "001",
    "fecha_emision": "2026-08-16T15:30:00-03:00",
    "moneda": "PYG",
    "cliente": {"ruc": "80000000-0", "razon_social": "Cliente prueba"},
    "items": [{"descripcion": "Servicio", "cantidad": 1, "precio_unitario": 1000}]
  }
}
```

No enviar `numero`, `generated_xml`, `signed_xml` ni `doc_id`. KilaSifen reserva
el número fiscal atómicamente; XML controlado por caller se rechaza. `external_id`
mapea el objeto ERP. Reutilizar `idempotency_key` al reintentar la misma intención.

- primera creación: `201 Created`;
- replay idempotente: `200 OK`, mismo documento/job;
- contenido incompatible: `409 Conflict`.

La respuesta trae documento `queued` y job; no implica aprobación. Estados de
documento: `queued`, `submitted`, `retry_pending`, `reconciliation_required`,
`approved`, `approved_with_observation`, `rejected`, `failed`, `cancelled`.
Jobs: `queued`, `retry_scheduled`, `succeeded`, `failed`.

Cliente, ítems, IVA, descuentos/anticipos, moneda/tipo de cambio y condición de
pago se validan de forma anidada antes de reservar el job. Un `422` significa que
la intención no ingresó a la cola. Los aliases históricos `razonSocial`,
`precioUnitario` e `iva` se normalizan a `snake_case` para compatibilidad.

## Nota de crédito

`POST /v1/emitters/{emitter_id}/documents/notas-credito` usa wrapper
`nota_credito`, igual idempotencia/numeración, y requiere `cliente`, `items` y
`documento_asociado` (con `cdc` para DTE electrónico).

## Nota de débito

`POST /v1/emitters/{emitter_id}/documents/notas-debito` usa wrapper
`nota_debito`. Comparte el contrato fiscal base, idempotencia y numeración
atómica, y exige `documento_asociado`. El motivo `recupero_costo` se normaliza al
código SIFEN `6`; también se aceptan los códigos `1..8` del Manual Técnico 150.

## Lecturas y operaciones fiscales

```text
GET  /v1/emitters/{emitter_id}/documents/{document_id}
GET  /v1/emitters/{emitter_id}/jobs/{job_id}
GET  /v1/emitters/{emitter_id}/documents/{document_id}/xml
GET  /v1/emitters/{emitter_id}/documents/{document_id}/kude
GET  /v1/emitters/{emitter_id}/documents/{document_id}/kude/data
POST /v1/emitters/{emitter_id}/queries/documents/{document_id}/reconcile
POST /v1/emitters/{emitter_id}/documents/{document_id}/cancel
POST /v1/emitters/{emitter_id}/inutilizations
GET  /v1/emitters/{emitter_id}/events/{event_id}
```

Cancelación usa `{"motivo": "..."}`; inutilización usa timbrado, tipo,
establecimiento, punto, rango y motivo. Ambas crean un event/job `queued` con
`201`; el worker `events` transmite a SIFEN y el ERP consulta el evento/job o
recibe el webhook terminal. Los endpoints raw `/documents` y `/events` están
deprecados y son sólo admin.

Ante timeout o respuesta ambigua de emisión, Kila persiste el CDC, XML firmado y
request exactos, y consulta SIFEN sin volver a transmitir el DE. Después de
agotar la reconciliación automática queda `reconciliation_required`; el ERP usa
el endpoint `reconcile` con la misma intención original. Ni el worker ni una
recola manual pueden reenviar ese CDC.

## Sandbox determinístico

Sólo cuando `KILA_SIFEN_ENVIRONMENT=test`, una emisión puede solicitar un
resultado reproducible con `X-Kila-Test-Outcome`: `approved`,
`approved_with_observation` o `rejected`. El XML, CDC, firma, persistencia y
workers reales siguen ejecutándose; únicamente se sustituye el transporte de
red a SIFEN. El mismo header es rechazado en staging y producción.

## Recibo Electrónico de Dinero

No existe endpoint fiscal de Recibo en v1. El Decreto 872/2023 lo define, pero el
Manual Técnico 150 vigente no publica su formato y `siRecepRDE_v150.xsd` depende
de `rde/150/RDE_Group.xsd`, actualmente ausente del servidor oficial. No se usa
`iTiDE=8`: ese código corresponde a Comprobante de Retención Electrónico.

La decisión y condición de habilitación están en
[adr-0002-recibo-electronico.md](architecture/adr-0002-recibo-electronico.md).

## Webhooks

Registrar URL HTTPS pública, secreto aleatorio ≥32 caracteres, suscripciones y
`retry_policy.max_attempts` (1..8) en
`POST /v1/emitters/{emitter_id}/webhooks`. La respuesta sólo informa
`secret_configured`. Firma exacta, replay y backoff:
[integrations/webhooks.md](integrations/webhooks.md).

El ERP actualiza por webhook y usa polling de documento/job como recuperación.

## Compatibilidad

Dentro de `/v1`, cambios son aditivos. Remover/renombrar o cambiar semántica exige
`/v2` y guía de migración. Clientes ignoran campos desconocidos; requests tipados
se validan estrictamente. No existe integración con FacturaSend.
