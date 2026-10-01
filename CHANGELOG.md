# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses semantic versioning principles.

## [0.2.0] - Unreleased

Esta versión cambia el nombre del paquete del engine, de varios módulos y de
las clases de transmisión, sin alias de compatibilidad. Antes de actualizar,
revisar la guía de migración de esta sección.

### Breaking changes

- El engine se importa como `kilasifen.engine`. El paquete `pysifen` dejó de
  existir y la distribución ya no lo incluye.
- Se eliminó `kilasifen.engine.CommonMixin`. Las clases generadas desde los
  XSD heredan ahora de `kilasifen.engine.binding.BindingMixin`, que ofrece los
  mismos métodos: `from_xml`, `from_path`, `to_xml`, `validate_xml` y
  `sign_xml`. Cambian dos nombres de parámetro: `from_xml` recibe `xml` (antes
  `xml_string`) y `from_path` recibe `path` (antes `file_path`).
- Se eliminó el módulo `kilasifen.engine.assinatura`. La firma está en
  `kilasifen.engine.firma.sign_xml` y se sigue exportando como
  `kilasifen.engine.sign_xml`.
- El paquete `kilasifen.engine.transmissao` fue reemplazado por
  `kilasifen.engine.transmision`. `TransmissaoBase`, `TransmissaoDE` y
  `TransmissaoEvento` pasan a ser `TransmisionBase`, `TransmisionDE` y
  `TransmisionEvento`; `ConsultaSIFEN` conserva su nombre. No quedan alias con
  los nombres anteriores, tampoco en la fachada `kilasifen.engine`.
- El segundo parámetro de `get_endpoint` se llama `servicio` (antes
  `servico`). Solo afecta a las llamadas que lo pasan por nombre.
- El extra de instalación `transmissao` ahora se llama `transmision`.
- Los adaptadores de la plataforma en `kilasifen.infrastructure.sifen`
  reemplazan el prefijo `Pysifen` por `KilaSifen`: `KilaSifenEmissionEngine`,
  `KilaSifenDocumentTransport`, `KilaSifenEventGateway`,
  `KilaSifenQueryGateway`, `KilaSifenPayloadMapper` y `KilaSifenEmissionInput`.
- Los bindings se generan con `scripts/generate_bindings.py` (xsdata 26.2, con
  la configuración dentro del script y un modo `--check` que detecta deriva
  sin escribir). Se eliminaron `script.sh` y `.xsdata.xml`.
- Muestras de `kilasifen/engine/de/samples/v150/`: ya no se distribuyen
  `factura_exportacion.xml`, `factura_importacion.xml` ni
  `comprobante_retencion.xml`, porque `DE_Types_v150.xsd` no admite los tipos
  2, 3 y 8 (el patrón es `1|[4-7]|9|10` y sus descripciones están comentadas).
  Las cinco restantes (`factura_electronica`, `autofactura`,
  `nota_credito`, `nota_debito` y `nota_remision`, tipos 1, 4, 5, 6 y 7) se
  rehicieron con datos ficticios nuevos, así que cambian CDC, RUC, nombres,
  ítems y totales.
- Los mensajes de error de `kilasifen.engine.transmision`,
  `kilasifen.engine.firma` y del firmador PKCS12
  (`kilasifen.engine.sdk.signer`) ahora están en español. El código que compare
  el texto de esos mensajes tiene que ajustarse. Queda una excepción:
  `SifenUnexpectedResponseError`, que la transmisión lanza pero se define en
  `kilasifen.engine.sdk.errors`, sigue con su texto en inglés.
- Los extras `sign` y `transmision` exigen `signxml>=5.1` (antes `>=3.0`).
- API de webhooks: `POST /v1/emitters/{emitter_id}/webhooks/{endpoint_id}/deliveries/replay`
  recibe sólo `{"delivery_id": "..."}` y reenvía una entrega que la plataforma
  ya generó para el mismo emisor (mismo `type`, `data` y `occurred_at`, con
  `delivery_id` nuevo). Los campos `event_type` y `payload` se rechazan con
  `422`. Para probar un endpoint existe
  `POST /v1/emitters/{emitter_id}/webhooks/{endpoint_id}/test`, que envía el
  evento sintético `webhook.test`. En el SDK TypeScript, `WebhookReplayInput`
  pasa a ser `{ delivery_id }` y se agrega `webhooks.sendTestEvent`. Es un
  cambio de semántica dentro de `/v1` justificado por seguridad (ver la
  sección Security).

### Guía de migración

La columna "Antes" usa los nombres bajo `kilasifen.engine`. Si el código
todavía importa `pysifen`, aplicar primero la primera fila y después el resto.

| Antes | Ahora |
| --- | --- |
| `import pysifen`, `from pysifen.<módulo> import ...` | `import kilasifen.engine`, `from kilasifen.engine.<módulo> import ...` |
| `kilasifen.engine.CommonMixin` | `kilasifen.engine.binding.BindingMixin` |
| `from_xml(xml_string=...)`, `from_path(file_path=...)` | `from_xml(xml=...)`, `from_path(path=...)` |
| `from kilasifen.engine.assinatura import sign_xml` | `from kilasifen.engine.firma import sign_xml` o `from kilasifen.engine import sign_xml` |
| `kilasifen.engine.transmissao` | `kilasifen.engine.transmision` |
| `TransmissaoBase` | `TransmisionBase` (en `kilasifen.engine.transmision.base`) |
| `TransmissaoDE` | `TransmisionDE` |
| `TransmissaoEvento` | `TransmisionEvento` |
| `get_endpoint(ambiente, servico=...)` | `get_endpoint(ambiente, servicio=...)` |
| `pip install "kilasifen[transmissao]"` | `pip install "kilasifen[transmision]"` |
| `Pysifen<Nombre>` en `kilasifen.infrastructure.sifen.{engine,event,mapper,query}` | `KilaSifen<Nombre>` en el mismo módulo (por ejemplo, `PysifenEmissionEngine` pasa a `KilaSifenEmissionEngine`) |
| `./script.sh` junto con `.xsdata.xml` | `python scripts/generate_bindings.py` (agregar `--check` para solo verificar) |
| `factura_exportacion.xml`, `factura_importacion.xml`, `comprobante_retencion.xml` | Sin reemplazo |
| Valores fijos copiados de las muestras anteriores (CDC, RUC, totales) | Leerlos de las muestras nuevas; los tests del repositorio los declaran en `tests/_muestras.py` |
| Comparar el texto de un mensaje de error del engine | Comparar por tipo de excepción; los textos cambiaron |
| `signxml>=3.0` | `signxml>=5.1` |
| `POST .../deliveries/replay` con `{"event_type", "payload"}` (o `webhooks.replay(..., { event_type, payload })` en el SDK) | `POST .../webhooks/{endpoint_id}/test` (`webhooks.sendTestEvent`) para probar el endpoint; `{"delivery_id": "..."}` para reenviar una entrega existente |

### Added

- API fiscal *headless* (`kilasifen.api`) sobre PostgreSQL, Redis/RQ y un
  outbox transaccional: emisores, certificados, timbrados, documentos
  tipados (factura, nota de crédito y nota de débito), eventos de
  cancelación e inutilización, consultas, KuDE, webhooks firmados y consola
  de administración.
- `SifenClient`, fachada de alto nivel del SDK para envío, consultas y
  eventos.
- Registro de esquemas determinista para validar contra los XSD.
- Utilidades de *polling* para lotes y para la consulta asíncrona de DTE.
- Ejemplos ejecutables en `docs/examples/`.

### Changed

- El transporte SOAP admite `close()` y uso como *context manager*, con
  timeouts, reintentos de consultas y reutilización de la sesión.
- El estado del PKCS12 se reutiliza entre firmas repetidas.
- La CI valida además los artefactos wheel/sdist y la API pública.
- `import kilasifen.engine` funciona sin ningún extra instalado: `requests`,
  `cryptography`, `lxml` y el cliente SOAP de xsdata se importan recién al
  firmar o transmitir. `sign_xml` y las operaciones de transmisión que no
  firman lanzan un `ImportError` que indica qué extra instalar
  (`kilasifen[sign]` o `kilasifen[transmision]`). No pasa lo mismo en todos
  los caminos: `BindingMixin.validate_xml` deja pasar el `ImportError`
  genérico de `lxml`, y si la firma ocurre dentro de `enviar_de`/`enviar_lote`
  o directamente en `kilasifen.engine.sdk.signer`, la dependencia faltante
  llega como `SifenSignatureError`.
- `ConsultaSIFEN.consultar_de` exige un CDC de exactamente 44 dígitos ASCII
  (`0` a `9`) y lanza `ValueError` en otro caso. Antes también se aceptaban
  dígitos Unicode de otros sistemas de escritura.
- `TransmisionBase` y sus subclases lanzan `ValueError` al construirse si
  `max_retries` es negativo. El valor por defecto sigue siendo `0`.
- El firmador PKCS12 acepta `bytearray` y `memoryview`, además de `bytes`,
  para el contenido del certificado, la contraseña y el documento a firmar.
- El autor declarado en los metadatos del paquete es "The KilaSifen Authors".
- `tests/conftest.py` usa `timezone.utc` en vez de `datetime.UTC`, que no
  existe en Python 3.10, la versión más baja de la matriz de CI. Eso solo no
  alcanza para que el job del engine (`pytest tests/test_*.py`) pase en 3.10:
  `tests/test_logging.py` y `tests/test_observability.py` importan la
  plataforma, que usa `datetime.UTC` en 18 módulos y en la práctica necesita
  Python 3.11 o posterior.
- La API responde con el envelope de error documentado (`code`, `category`,
  `message`, `correlation_id`, `details`) también ante errores del framework:
  validación del request (`422 request.validation_failed`, con los campos en
  `details.errors` y sin devolver el valor enviado), ruta inexistente
  (`404 request.route_not_found`), método no permitido
  (`405 request.method_not_allowed`, conserva `Allow`) y fallos inesperados
  (`500 server.internal_error`, con `X-Correlation-ID`). Antes salían como
  `{"detail": ...}` o como texto plano. El contrato OpenAPI declara
  `ErrorEnvelope` en las respuestas `401`, `403`, `404`, `422`, `429` y `503`
  de las rutas autenticadas, más `409` y `413` (`request.body_too_large`) en
  los grupos de rutas que modifican recursos, y ya no publica
  `HTTPValidationError`.
- El `429` del límite por credencial (`limits.rate_exceeded`,
  `limits.concurrency_exceeded`) trae el header `Retry-After`, como ya lo
  traía el límite previo a la autenticación, y el contrato OpenAPI lo declara
  en todas las respuestas `429`.
- SDK TypeScript: una respuesta de error sin envelope (por ejemplo el `502`
  HTML de un proxy) ya no se reporta como
  `KilaSifenConnectionError("sdk.invalid_response")` no reintentable, sino con
  el código nuevo `sdk.http_error`, que conserva `status` y `correlationId` y
  es reintentable para `408`, `425`, `429` y `5xx`. `KilaSifenConnectionError`
  suma las propiedades `status` y `correlationId` (`null` cuando no aplican).
  Los envelopes de error de cualquier `4xx`, incluido `422`, siguen llegando
  como `KilaSifenError` con sus `details`.

### Security

- Firmador XMLDSig (`kilasifen.engine.sdk.signer`) reescrito desde la
  especificación:
  - rechaza documentos con `DOCTYPE` y parsea sin resolver entidades, sin
    acceso a la red y sin cargar DTD;
  - no modifica el árbol `lxml` que recibe: firma una copia parseada de nuevo;
  - si un ancestro declara un prefijo para el namespace XMLDSig
    (`xmlns:ds`), la `Signature` mantiene su propia declaración por defecto y
    la firma sigue verificando.
- El replay de webhooks ya no permite forjar eventos: antes, una credencial
  con sólo `tenant:write` podía enviar cualquier `event_type` y `payload`
  firmados con el HMAC del endpoint (por ejemplo, un `document.approved`
  falso). Ahora sólo reenvía entregas existentes del mismo emisor, y el evento
  de prueba `webhook.test` tiene `data` fija fuera de los espacios fiscales.
  Las entregas creadas con el contrato anterior quedan almacenadas sin cambios.
  El endpoint destino tiene que estar suscripto al tipo del evento
  (`409 webhooks.event_not_subscribed`), con las mismas reglas que al
  publicarlo, y la documentación pide ordenar por `occurred_at`, que el replay
  conserva.
- La ruta raw deprecada `POST /v1/emitters/{emitter_id}/documents` (sólo
  `platform:admin`) ya no funciona como oráculo de firma ni como canal de XML
  ajeno: rechaza `signed_xml` (también dentro de `typed_contract`) con
  `422 documents.raw.signed_xml_not_allowed` y exige que `generated_xml` sea un
  `rDE` sin `DOCTYPE` que valide contra el XSD oficial
  (`documents.raw.generated_xml_*`). Los hijos del `rDE` tienen que ser, en
  orden, `dVerFor`, un solo `DE`, una `Signature` opcional (la plataforma la
  reemplaza al firmar) y `gCamFuFD`, sin ningún otro elemento
  (`documents.raw.generated_xml_unexpected_element`). La validación usa una
  copia con una `Signature` de relleno, para que libxml2 valide también lo que
  sigue al `DE`. La firma referencia siempre el `Id` de ese `DE`: un `doc_id`
  distinto se rechaza con `documents.raw.doc_id_mismatch` y, si falta, se toma
  del `DE`. El worker vuelve a aplicar la misma política antes de firmar e
  ignora cualquier `signed_xml` del payload: sólo reutiliza el XML que la propia
  plataforma firmó en un intento anterior. La política se aplica después de la
  búsqueda por `Idempotency-Key` y `external_id`, así que el reintento de un
  documento raw creado antes de este cambio sigue recibiendo su replay `200`
  (o el mismo `409`) en lugar de un `422`.
  - Antes de desplegar, listar los documentos raw `queued` o `processing` cuyo
    `payload_snapshot` traiga `signed_xml` y ninguno firmado por la plataforma
    (`documents.signed_xml` vacío): el worker ahora los marca `failed`
    (`fiscal_validation`). Si alguno pudo llegar al SIFEN (una caída entre el
    envío y el commit), consultar su CDC en el SIFEN antes de desplegar.
- Las claves privadas descifradas ya no quedan residentes en los workers: los
  jobs de documentos y de eventos vacían la caché de firmadores PKCS12
  (`kilasifen.engine.sdk.signer.clear_pkcs12_signer_cache`) al terminar,
  también cuando fallan. Antes, un worker que no hace fork por job
  (`CrossPlatformSimpleWorker`, el de Windows) conservaba la clave de un
  certificado reemplazado o desactivado hasta el desalojo del LRU o un
  reinicio. Con el `rq worker` por defecto la caché ya moría con cada work
  horse. Cada job paga ahora una decodificación del PKCS12.
- Como defensa en profundidad, activar un certificado también vacía la caché
  del proceso de la API. Ese proceso no firma documentos ni eventos (los firman
  los workers), y la limpieza ocurre antes del commit de la activación.
- `SECURITY.md` deja un solo canal para reportar vulnerabilidades: el
  private vulnerability reporting de GitHub. Se quitó el correo del mantenedor
  anterior, que figuraba como segunda opción.

### Documentation

- Matriz de trazabilidad normativa en `docs/normativa/matriz.md`.
- Documentos de contribución y de política de seguridad.
- README, `CLAUDE.md` y la guía de API pública reescritos desde cero contra
  el código actual, con sus limitaciones conocidas.
- `errores.mdx` lista los valores de `category` (incluido `invalid_request`)
  y aclara que los `details.errors` de la ruta raw pueden citar valores del
  XML enviado.
- `docs/examples/kila_api_emit_document.py` (ruta raw, sólo admin) lee el
  `rDE` sin firmar de `KILA_RDE_XML_PATH` en lugar de enviar `<rDE/>`, que la
  ruta ahora rechaza, y muestra el código de un `422`.

## [0.1.1] - 2026-04-22

### Added

- stable top-level public API facade.

### Changed

- README normalization and public API documentation updates.
