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
  "ruc": "44444401",
  "dv": "7",
  "legal_name": "Empresa SA",
  "tax_environment": "test",
  "fiscal_profile": {
    "tipo_contribuyente": 2,
    "actividades_economicas": [
      {"codigo": "62010", "descripcion": "ACTIVIDADES DE PROGRAMACION INFORMATICA"}
    ],
    "domicilio": {
      "direccion": "CALLE EJEMPLO",
      "numero_casa": "123",
      "departamento": 1,
      "ciudad": 1,
      "descripcion_ciudad": "ASUNCION (DISTRITO)",
      "telefono": "021123456",
      "email": "facturacion@example.com"
    },
    "establecimientos": []
  }
}
```

El RUC tiene 3-8 caracteres (`tRuc`), `dv` es el módulo 11 del RUC,
`legal_name` tiene 4-255, el CSC 32 caracteres alfanuméricos y `csc_id` 1-9999
(se guarda con cuatro dígitos). Un dato inválido responde `422`.

`fiscal_profile` es la única fuente de `gEmis`: tipo de contribuyente, régimen
y nombre de fantasía opcionales, de 1 a 9 actividades económicas y el domicilio
del RUC (`numero_casa` `0` si no tiene numeración; el departamento se valida
contra el XSD de departamentos y su descripción se completa sola). Cada
establecimiento con otra dirección se agrega en `establecimientos` con su
código `dEst`. Puede cargarse después con `PATCH /v1/emitters/{id}`, que lo
reemplaza completo; mientras falte, `fiscal_profile_complete` es `false` y
crear un documento tipado responde `422 emitters.fiscal_profile_required`.

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
    "fecha_emision": "2026-10-01T15:30:00-03:00",
    "moneda": "PYG",
    "cliente": {
      "ruc": "80025298-5",
      "tipo_contribuyente": 2,
      "razon_social": "Cliente prueba"
    },
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
`failed`, `cancelled`.
Jobs: `queued`, `processing` (un worker está en medio de un intento),
`retry_scheduled`, `succeeded`, `failed`.

Cliente, ítems, IVA, descuentos/anticipos, moneda/tipo de cambio y condición de
pago se validan de forma anidada antes de reservar el job. Un `422` significa que
la intención no ingresó a la cola. Los aliases históricos `razonSocial`,
`precioUnitario` e `iva` se normalizan a `snake_case` para compatibilidad.

Reglas fiscales que se validan al crear (fuentes en `docs/normativa/matriz.md`):

- `emisor` es opcional y sólo puede repetir la identidad del emisor
  (`ruc`, `dv`, `razon_social`, y `tipo_contribuyente` en la raíz); si no
  coincide responde `422 documents.emisor.identity_mismatch`. Sus campos de
  dirección, contacto y actividad están obsoletos y se ignoran.
- `cliente` con RUC exige `tipo_contribuyente` y un DV correcto (`RUC-DV` o
  `dv`). Un no contribuyente sólo puede ser B2C o B2F, y siempre envía
  `tipo_documento_identidad` y `numero_documento_identidad` (con 9, además
  `descripcion_tipo_documento`). B2F exige `pais_codigo` distinto de `PRY` y
  `direccion` con `numero_casa`; fuera de B2F, una dirección exige
  `departamento`, `ciudad` y `descripcion_ciudad`. `compras_publicas` es
  opcional en B2G.
- Innominado (`tipo_documento_identidad` 5): sólo en facturas B2C; se escribe
  con número `0` y nombre `Sin Nombre`, y el worker lo rechaza desde 7.000.000
  Gs (salvo muestras médicas).
- `codigo_seguridad` es opcional: si se omite, KilaSifen genera uno aleatorio y
  lo conserva en todos los reintentos. No puede ser `0` ni igual al número.
- `fecha_emision` tiene que estar entre 720 h antes y 120 h después de ahora
  (hora oficial de Paraguay, UTC−3). Si queda a más de 120 h, el documento se
  crea igual pero `fiscal_warnings` avisa que el SIFEN lo aprobará con la
  observación 1005 (transmisión extemporánea).
- `moneda` (y la de cada pago o cuota) es un código ISO 4217 de
  `Monedas_v150.xsd`; las descripciones del XML son su nombre oficial
  (`Guarani`, `US Dollar`). `formas_pago[].moneda_descripcion` se ignora.
- IVA por ítem: `afectacion` `gravado` (proporción 100), `exento` o
  `exonerado` (proporción 0, `tasa` 0) y `gravado_parcial`, que exige
  `proporcion_gravada` entre 0 y 100 sin incluirlos. Base gravada, IVA y base
  exenta salen de las fórmulas de la NT 13 con hasta 8 decimales, también en
  PYG; los totales son la suma exacta de los ítems.
- Descuento global: `porcentaje_descuento_global` (0 por defecto) se aplica a
  cada ítem como `porcentaje * precio_unitario / 100`. `items[].descuento_global`
  es opcional y, si se envía, tiene que coincidir con ese cálculo (±0,8).
- Redondeo: `redondeo` es `ninguno` (por defecto, `dRedon` 0) o `multiplo_50`
  (sólo PYG): baja `dTotOpe` al múltiplo de 50 Gs anterior. Nunca se redondea
  una moneda extranjera.
- Pagos (sólo facturas): en contado, `formas_pago` tiene que sumar el total
  neto (tolerancia 0,50) y sin `formas_pago` se informa un pago en efectivo
  por el total. A crédito, `formas_pago` sólo va con
  `credito.monto_entrega_inicial` y tiene que sumarlo. Un pago sin `moneda` es
  en la moneda de la operación; `tipo_cambio` es obligatorio si el pago no es
  en PYG (si va en la moneda de la operación se usa el `tipo_cambio` del
  documento) y no se admite si es en PYG.
- `tipo_impuesto` 2 (ISC) no se admite.

Los incumplimientos responden `422` con el código de la regla en el mensaje,
por ejemplo `documents.items.proporcion_gravada_required`,
`documents.redondeo.only_pyg` o
`documents.condicion_operacion.formas_pago.total_mismatch`.

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

El KuDE (`/kude` en PDF y `/kude/data` en JSON) sale del XML firmado y se
entrega para documentos `approved*` y para los que siguen en camino al SIFEN
(`queued`, `processing`, `submitting`, `submitted`, `retry_pending`,
`reconciliation_required`): con validación posterior puede entregarse antes
de la aprobación, pero sólo vale si el SIFEN aprueba el DE (MT v150 §6.2 y
§6.4). Para `rejected`, `failed`, `inutilized`, `cancelled` o cualquier otro
estado responde `409 documents.kude_not_available` con
`details.internal_status`. El PDF lleva el QR en la primera página, páginas
`n/total`, la fecha de inicio del timbrado como `DD-MM-AAAA` (NT 10), el
«Total en Guaraníes» (`dTotalGs` si la moneda no es PYG) y las cantidades
y los montos con todos los dígitos del XML, sin redondear (MT v150 §13.2 y
§6.6): sólo cambian los separadores (`952.38095238` se imprime
`952,38095238`).
`/kude/data` devuelve los literales del XML: `totales.total_general_operacion`
es `dTotGralOpe` y `totales.total_general_guaranies` es `dTotalGs` fuera de
PYG. El `qr.url` es el `dCarQR` del XML, calculado con los valores literales
del XML firmado (MT v150 §13.8; con un receptor no contribuyente el
parámetro es `dNumIDRec`).

Cancelación usa `{"motivo": "..."}`; inutilización usa timbrado, tipo,
establecimiento, punto, rango y motivo. Ambas crean un event/job `queued` con
`201`; el worker `events` transmite a SIFEN y el ERP consulta el evento/job o
recibe el webhook terminal. Los endpoints raw `/documents` y `/events` están
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
timeout, respuesta ambigua o caída del worker durante el envío, consulta SIFEN
por CDC sin volver a transmitir el DE. Después de agotar la reconciliación
automática queda `reconciliation_required`; el ERP usa el endpoint `reconcile`
con la misma intención original. Ni el worker ni una recola manual pueden
reenviar ese CDC. Sólo cuando la falla prueba que el request no salió
(`transport_not_sent` en el job) el documento vuelve a `queued` y se reenvía el
mismo request; si se agotan los intentos, el job queda `failed` y el documento
`queued`, listo para un reintento manual.

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
`/v2` y guía de migración. La excepción son las correcciones exigidas por la
normativa fiscal (por ejemplo el perfil fiscal del emisor o las reglas del
receptor de 0.2.0): se documentan en el CHANGELOG con su guía de migración. Clientes ignoran campos desconocidos; requests tipados
se validan estrictamente. No existe integración con FacturaSend.
