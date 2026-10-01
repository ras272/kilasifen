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

El RUC es una identidad global de plataforma. Por eso sólo una credencial con
`platform:admin` puede darlo de alta y asignarlo al consumidor en una operación:

```json
POST /v1/emitters
{
  "owner_consumer_id": "consumer_uuid",
  "ruc": "80024135",
  "dv": "5",
  "legal_name": "Empresa SA",
  "tax_environment": "test"
}
```

Compatibilidad: la ruta y el resto del payload no cambian; si
`owner_consumer_id` se omite, el emisor queda asignado al consumidor de la clave
administradora. Desde esta versión, una clave tenant que intentaba crear un
emisor recibe `403 auth.insufficient_scope`. Lecturas y actualizaciones de
emisores ya asignados conservan sus scopes anteriores.

`POST /v1/emitters/{id}/deactivate` es un kill switch. Un emisor inactivo sigue
siendo legible y permite corregir metadatos no secretos, pero toda nueva
operación fiscal o con secretos responde `409 emitters.inactive`. Los workers ya
encolados aplican la misma regla antes de descifrar, firmar o contactar SIFEN o
un webhook.

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
payload; `429` límite (esperar `Retry-After` segundos); `503` dependencia.
Conservar `correlation_id`. Un `503` `emitters.lock_timeout` o
`numbering.lock_timeout` significa que otra operación del mismo emisor retuvo
el bloqueo más de 5 s: la intención no se registró y se reintenta con backoff
y la misma `idempotency_key`.

El mismo envelope cubre los errores del framework y el contrato OpenAPI lo
declara (`ErrorEnvelope`) en cada ruta autenticada:

- `422 request.validation_failed`: body, query o path inválidos. Los campos van
  en `details.errors` como `{loc, message, type}`; el valor enviado nunca se
  devuelve.
- `404 request.route_not_found` y `405 request.method_not_allowed` (con header
  `Allow`): ruta o método inexistente.
- `413 request.body_too_large`: body por encima del límite configurado.
- `500 server.internal_error`: fallo inesperado, con `correlation_id` y header
  `X-Correlation-ID`, sin detalle interno. Reintentar con backoff.

Un `502`/`504` de un proxy puede llegar sin JSON: tratarlo como `5xx`
reintentable.

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
documento: `queued`, `submitting`, `submitted`, `retry_pending`,
`reconciliation_required`, `approved`, `approved_with_observation`, `rejected`,
`failed`, `cancelled`, `inutilized`. La respuesta de SIFEN se lee por `dEstRes`
(sin tildes ni mayúsculas): «Aprobado con observación» es un DTE válido
(`approved_with_observation`), y sin `dEstRes` solo `0260` prueba una
aprobación.
Jobs: `queued`, `processing` (un worker está en medio de un intento),
`retry_scheduled`, `succeeded`, `failed`.

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

Cancelación usa `{"motivo": "..."}`; inutilización usa timbrado (del emisor),
tipo, establecimiento, punto, rango, motivo y `serie` opcional (`dSerieNum`).
Ambas crean un event/job `queued` con `201`; el worker `events` transmite a
SIFEN y el ERP consulta el evento/job o recibe el webhook terminal. Un evento
queda registrado solo con `0600`. La cancelación vence 48 h (factura) o 168 h
(otros DTE) después de la aprobación en SIFEN, no admite una segunda solicitud
mientras otra pueda registrarse (`409 events.cancel.already_pending`) y, ante
una respuesta perdida o un rechazo `4002`/`4003`/`4009`/`4010`, consulta el CDC
(`xContEv`) antes de reenviar o de creer el rechazo. La inutilización acepta
números sin documento, rechazados, fallidos o en cola abortados, nunca un DTE
ni un documento que pueda estar en SIFEN; no tiene tope de días (pasado el día
15 del mes siguiente responde `warnings: ["inutilization.extemporaneous"]`) y,
al aprobarse, deja esos documentos en `inutilized`. Los endpoints raw `/documents` y `/events` están
deprecados y son sólo admin. En el raw `/documents`, `payload.generated_xml`
tiene que ser un `rDE` sin firmar que valide contra el XSD oficial (sin
`DOCTYPE`), con `dVerFor`, un solo `DE`, una `Signature` opcional y
`gCamFuFD` como únicos hijos; KilaSifen firma ese `DE` con el certificado del
emisor. `payload.doc_id` es opcional y, si se envía, tiene que ser el `Id` de
ese `DE` (`422 documents.raw.doc_id_mismatch`). Un `signed_xml` provisto por
el caller se rechaza con `422 documents.raw.signed_xml_not_allowed`: la
plataforma sólo transmite XML que firmó ella misma. Los `details.errors` de
`documents.raw.generated_xml_invalid_schema` son mensajes del validador XSD y
pueden citar valores del XML enviado.

Kila confirma en la base el CDC, el XML firmado y el request exacto (con su
`dId` real) antes de transmitir, con el documento en `submitting`. Ante
timeout, respuesta ambigua o caída del worker durante el envío, el intento
siguiente consulta SIFEN por CDC: con `0422` el documento queda aprobado y no se
reenvía; con `0420` («no existe o no está aprobado») vuelve a `queued` y el
intento siguiente reenvía el mismo DE firmado (mismo CDC y firma) en un
`rEnviDe` con `dId` nuevo (Decreto 872/2023 Art. 29). Un rechazo `1001`/`1002`
solo queda firme después de esa consulta, y uno `0161`/`0162` (falla del
servidor) se reenvía. Si al agotar los intentos SIFEN no dio una respuesta
sobre el CDC, el documento queda `reconciliation_required`; el ERP usa el
endpoint `reconcile` con la misma intención original. Cuando la falla prueba
que el request no salió (`transport_not_sent` en el job) el documento vuelve a
`queued` y se reenvía el mismo DE firmado; si se agotan los intentos, el job
queda `failed` y el documento `queued`, listo para un reintento manual.
Mientras SIFEN no aprueba un documento, el job avisa en
`error_snapshot.deadline_alerts` cuando se acercan o pasan las 72 h desde la
firma (observación `1005`) o las 720 h desde la emisión (rechazo `1150`). El
timbrado se elige con la fecha de emisión (`dFeEmiDE`), no con la del
servidor.

## Sandbox determinístico

Sólo cuando `KILA_SIFEN_ENVIRONMENT=test`, una emisión puede solicitar un
resultado reproducible con `X-Kila-Test-Outcome`: `approved`,
`approved_with_observation`, `rejected`, `transport_timeout` o
`accepted_but_response_lost`. El XML, CDC, firma, persistencia y workers reales
siguen ejecutándose; únicamente se sustituye el transporte de red a SIFEN. El
mismo header es rechazado en staging y producción.

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

`POST .../webhooks/{endpoint_id}/test` envía un evento sintético
`webhook.test` para verificar el endpoint. El replay
(`POST .../webhooks/{endpoint_id}/deliveries/replay`) recibe sólo
`{"delivery_id": "..."}` y reenvía un evento ya generado para el mismo emisor;
desde 0.2.0 ya no acepta `event_type` ni `payload` del caller (`422`).

El ERP actualiza por webhook y usa polling de documento/job como recuperación.

## Compatibilidad

Dentro de `/v1`, cambios son aditivos. Remover/renombrar o cambiar semántica exige
`/v2` y guía de migración. Clientes ignoran campos desconocidos; requests tipados
se validan estrictamente. No existe integración con FacturaSend.
