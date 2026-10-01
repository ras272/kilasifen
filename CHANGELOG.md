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
  el texto de esos mensajes tiene que ajustarse. Eso incluye
  `SifenUnexpectedResponseError` (definida en `kilasifen.engine.sdk.errors`):
  su mensaje pasa de `Unexpected SIFEN response: expected X, received Y` a
  `Respuesta inesperada del SIFEN: se esperaba X y se recibio Y`.
- Los extras `sign` y `transmision` exigen `signxml>=5.1` (antes `>=3.0`).
- Plataforma: `DocumentEmissionEngine.emit_document` se reemplaza por dos
  pasos, `prepare_document` (arma, firma y envuelve el `rEnviDe` sin tocar la
  red) y `submit_prepared(request_xml=...)` (envía ese texto sin cambios).
  `DocumentSubmissionTransport.submit` recibe `request_xml` en lugar de
  `signed_xml`. Se eliminan `EmissionOutcome` y
  `EmissionTransportUncertainError`; aparece `PreparedSubmission`. Solo afecta
  a quien implemente motores o transportes propios para los workers. Además,
  `prepare_document` rechaza con `SifenValidationError` un payload con XML ya
  firmado del que no se puede obtener el `Id` del DE (el CDC): el documento
  queda `failed` y no se envía nada. Antes ese XML se enviaba con el CDC
  vacío, y una respuesta perdida ya no se podía reconciliar.
- Plataforma: `EventSubmissionGateway.submit_event` se reemplaza por
  `prepare_event` y `submit_prepared(request_xml=...)`; aparece
  `PreparedEventSubmission` y `EventSubmissionOutcome` deja de llevar
  `generated_xml`, `signed_xml` y `request_xml`.
  `EventService.process_queued_event` se reemplaza por
  `begin_queued_event_attempt` y `record_event_attempt`, que el worker llama
  en transacciones separadas.
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
- Engine, lotes (decisiones F65 y F66; ver Fixed): `poll_lote_status` devuelve
  un `LoteResult` en lugar de la respuesta cruda y ya no acepta
  `pending_codes`. `PollingConfig` suma `initial_delay_seconds` y cambia sus
  valores por defecto a 600 s antes de la primera consulta, 600 s entre
  consultas, 48 h de espera y ningún tope de intentos (antes 2 s, 120 s y 60
  intentos). `SifenClient.enviar_lote_y_esperar` devuelve ese `LoteResult`,
  lanza `SifenRejectionError` si la recepción no fue `0300` y `SifenLoteError`
  si falta `dProtConsLote`. `enviar_lote` rechaza con `ValueError`, sin
  enviar, un lote que mezcle `iTiDE` o RUC emisores, repita un CDC, tenga un
  `rDE` sin `DE/@Id`, `iTiDE` o `dRucEm`, traiga blancos entre etiquetas o
  supere 1000 KB.
- Engine, consulta DTE: `poll_dte_async_status` ya no trae textos de
  "pendiente" por defecto (eran inventados); sin `pending_tokens` devuelve la
  primera respuesta. También espera `initial_delay_seconds` antes de la
  primera consulta.

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
| `poll_lote_status(...)` devolvía la respuesta de la consulta de lote | Leer `resultado.response` (última respuesta) y `resultado.documents` (un `LoteDocumentResult` por CDC); pasar `cdcs` y `consultar_de` para el paso a siConsDE tras `0364` o 48 h |
| `poll_lote_status(..., pending_codes=(...))` | Sin reemplazo: el único código pendiente es `0361` |
| `PollingConfig()` con 2 s, 120 s y 60 intentos | `PollingConfig()` con 600 s, 48 h y sin tope; en pruebas, `PollingConfig(initial_delay_seconds=0, interval_seconds=0)` o `clock`/`sleep` simulados |
| `poll_dte_async_status(...)` con `PENDIENTE`, `EN PROCESO` y `PROCESANDO` por defecto | Pasar `pending_tokens=(...)` explícitos; el servicio es experimental |

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
- Engine, lotes: `TransmisionDE.enviar_lote_xml` (y `SifenClient.enviar_lote_xml`)
  envía en lote `rDE` ya firmados. `ConsultaSIFEN.consultar_lote(cdc=...)`
  consulta un lote por uno de sus CDC cuando no llegó el número de lote
  (XSD `WS_SiConsLote_v141.xsd`, `dCDC`; Guía de mejores prácticas de la DNIT,
  oct-2024, p. 6, punto 3). `kilasifen.engine.sdk` exporta `LoteResult`,
  `LoteDocumentResult`, `require_lote_protocol`, `classify_lote_response`,
  `lote_document_results`, `consulta_de_result` y `SifenLoteError`.
  `kilasifen.engine.transmision.de` expone `MAX_BYTES_MENSAJE_LOTE` y
  `NOMBRE_ARCHIVO_LOTE`.
- Engine: `SifenExperimentalWarning` y
  `kilasifen.engine.transmision.config.SERVICIOS_EXPERIMENTALES`.
- Ejemplos ejecutables en `docs/examples/`.
- `SifenRequestNotSentError` (subclase de `SifenTransportError`, exportada en
  `kilasifen.engine.sdk`): el transporte la lanza cuando la falla prueba que
  la solicitud nunca llegó al SIFEN (DNS, conexión rechazada o inalcanzable,
  tiempo agotado al conectar, handshake TLS fallido). Los errores que pueden
  ocurrir después de enviar el cuerpo (timeout de lectura, conexión cortada,
  respuesta truncada) siguen siendo `SifenTimeoutError` o
  `SifenTransportError`. Un `requests.ConnectTimeout` ahora se informa con
  esta excepción y ya no como `SifenTimeoutError`.

### Changed

- El transporte SOAP admite `close()` y uso como *context manager*, con
  timeouts, reintentos de consultas y reutilización de la sesión.
- Engine: la consulta DTE sincrónica y asincrónica (`consultar_dte`,
  `consultar_dte_async`) queda marcada como experimental y emite
  `SifenExperimentalWarning`. Solo existen sus XSD: su dirección, sus códigos
  y sus plazos no figuran en el Manual Técnico v150 (§7.10, p. 41), en las
  notas técnicas 01 a 27, en la Guía de mejores prácticas (p. 5), en la Guía
  de pruebas (feb-2026, p. 6) ni en la FAQ de la DNIT (decisión F66).
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
- Los envíos con efecto fiscal (`TransmisionDE.enviar_de`, `enviar_de_xml`,
  `enviar_lote` y los envíos de `TransmisionEvento`) solo se reintentan ante
  `SifenRequestNotSentError`, aunque `max_retries` sea mayor que `0`: un
  timeout de lectura, un corte de conexión o un 5xx sin cuerpo XML salen en
  el primer intento. Antes, con `max_retries > 0`, esos errores provocaban un
  reenvío que podía duplicar la operación. `ConsultaSIFEN` conserva la
  política anterior y reintenta también esos errores.
- Un SOAP Fault (en HTTP 200 o 5xx), el sobre de otra operación, HTML de un
  proxy o un cuerpo que no se puede leer ya no escapan como `ParserError` o
  `TypeError` de xsdata: `enviar_de`, `enviar_de_xml`, `enviar_lote`,
  `enviar_evento` y todas las consultas lanzan
  `SifenUnexpectedResponseError` (subclase de `SifenTransportError`, es
  decir, resultado incierto). La excepción gana el atributo `raw_body`, con
  el comienzo del cuerpo recibido (hasta 4096 caracteres) como texto; no se
  incluye en el mensaje. Las respuestas se validan por el nombre de su raíz
  antes de parsearlas, y `consultar_ruc` reabre la conexión ante esta
  excepción en lugar de ante `ParserError`.
- Plataforma: la espera por el bloqueo de la fila del emisor (`SELECT ... FOR
  UPDATE`) queda acotada a 5 segundos en PostgreSQL (`lock_timeout` local a
  la transacción, restaurado después). Si se agota, la API responde `503`
  con el código `emitters.lock_timeout`, igual que `numbering.lock_timeout`
  en la numeración. En los workers, el job conserva su estado (`queued` o
  `retry_scheduled`), anota la categoría `emitter_busy` y se vuelve a
  despachar 30 segundos después, sin gastar un intento ni tocar el documento
  o el evento; así un reintento manual de un documento o evento `failed`, que
  solo reabre un job `queued`, no se pierde. En SQLite no cambia nada.
- Plataforma: las consultas de documento y de RUC y el endpoint `reconcile`
  ya no toman el bloqueo de la fila del emisor, así que no lo retienen
  mientras esperan al SIFEN. Después de la respuesta, la reconciliación
  relee el documento con `SELECT ... FOR UPDATE` y decide sobre el estado
  confirmado: si un worker registró un resultado mientras tanto, ya no se
  pisa.
- Plataforma: cada intento de emisión de un documento usa dos
  transacciones y no retiene ninguna, ni bloqueos de filas, mientras espera
  al SIFEN. La primera bloquea emisor, documento y job, cuenta el intento y
  confirma en la base el XML generado, el firmado, el `rEnviDe` exacto que va
  a viajar y el CDC, con el documento en el estado nuevo `submitting`. La
  segunda toma los bloqueos en el mismo orden (emisor, sin límite de espera
  para no perder la respuesta del SIFEN; después documento y job, releídos
  con `FOR UPDATE`) y registra el resultado sin pisar un estado terminal
  escrito mientras tanto. Los webhooks de estado se publican dentro de un
  savepoint: un error de base al publicar se registra en el log y ya no
  puede descartar el resultado (en PostgreSQL, la transacción abortada
  convertía el `COMMIT` en un `ROLLBACK` silencioso). Antes todo el job era una
  sola transacción confirmada después del SOAP: una caída, un `ParserError`
  o cualquier excepción que no fuera `SifenError` perdía el XML, el CDC y el
  contador de intentos, y el bloqueo del emisor se mantenía durante la
  llamada.
- Plataforma: el `rEnviDe` que se guarda en `sifen_request_xml` es el que se
  envía, con su `dId` real (antes se guardaba uno armado con `dId` 1 y se
  enviaba otro).
- Plataforma: los fallos del envío se clasifican. Si la falla prueba que la
  solicitud no salió (`SifenRequestNotSentError`, transporte cerrado), el
  documento vuelve a `queued` y el próximo intento reenvía el mismo request,
  sin consultar; al agotar los intentos el job queda `failed`
  (`retry_exhausted`) y el documento `queued`, listo para un reintento
  manual. Cualquier otro fallo (timeout, conexión cortada, SOAP Fault,
  respuesta ilegible, `ParserError`, error de programación) deja el resultado
  incierto: `retry_pending` y reconciliación por CDC. Ninguna falla de la
  llamada al SIFEN escapa del worker sin registrarse; una falla de la base de
  datos en la primera o en la segunda transacción sí escapa y deja el job
  `processing` y el documento `submitting`. Un intento incierto que agota el
  presupuesto pasa a `reconciliation_required` (antes podía quedar `failed` y
  un reintento manual lo reenviaba). Un documento que quedó en `submitting`
  (el worker murió, o falló la base al registrar) se reconcilia por CDC en el
  intento siguiente, que hoy tiene que lanzar un operador desde la consola:
  ningún proceso retoma esos jobs solo.
- Plataforma: los eventos (cancelación e inutilización) siguen el mismo
  esquema de dos transacciones. El worker guarda el grupo firmado
  (`signed_xml`, antes vacío) y el `rEnviEventoDe` exacto con el evento en
  `submitting` antes de enviarlo, y registra el resultado en una segunda
  transacción (emisor, evento y job, en ese orden, con los webhooks en un
  savepoint), sin retener el bloqueo del emisor durante la llamada. Un
  request que no salió deja el evento en `queued` (`transport_not_sent`);
  cualquier otro fallo, en `retry_pending` (`transport`). Una respuesta de
  eventos que no es `rRetEnviEventoDe` (SOAP Fault, HTML, cuerpo truncado)
  ahora es `SifenUnexpectedResponseError`, resultado incierto, y ya no un
  error de validación que marcaba el evento como `failed`. El reintento de
  un evento incierto sigue reenviándolo, como antes. Mientras un evento sigue
  en `submitting` y no pasaron cinco minutos desde que se guardó su request
  (el intento anterior puede seguir esperando al SIFEN), un intento nuevo
  del mismo job (reintento manual, despacho duplicado) no firma ni envía
  nada: el job conserva su estado, anota `attempt_in_flight` y se vuelve a
  despachar cuando vence esa ventana.
- Plataforma: el outbox ya no da por publicado un job cuando RQ todavía
  informa como `started` una ejecución anterior con el mismo id. Antes
  devolvía ese registro y marcaba la fila como publicada, así que un
  reintento manual de un job cuyo worker había muerto se perdía en silencio
  (el job quedaba `queued` y el documento `submitting`). Ahora la publicación
  se posterga (`jobs.outbox.publish_deferred`) con el backoff habitual del
  outbox hasta que RQ termina esa ejecución o la marca fallida.
- Plataforma: los workers de RQ y el proceso del outbox configuran el mismo
  logging JSON que la API (`configure_logging`, nivel de
  `KILA_SIFEN_LOG_LEVEL`) la primera vez que corre un job o arranca el
  sweeper. Antes solo inicializaban Sentry y sus `logger.info` se perdían
  (los errores salían como texto plano por el `lastResort` de Python). Las
  líneas propias de RQ (`rq.worker`) conservan su formato y ya no se
  duplican.
- La firma de un `rDE` ya no se invalida al armar el `rEnviDe` (defecto P3).
  `_build_enviar_de_request_xml` inserta el `rDE` como texto, con sus propias
  declaraciones de namespace y sus prefijos, en lugar de moverlo como árbol
  lxml (lxml quitaba las declaraciones repetidas en el padre y reexpresaba un
  `rDE` prefijado en el namespace por defecto). Además, `enviar_de` y
  `enviar_lote` serializan el binding con el namespace del SIFEN por defecto,
  sin el prefijo `ns0:`, antes de firmar. La firma verifica dentro del
  `rEnviDe` tanto con `enviar_de(rde)` como con `enviar_de_xml` de un `rDE`
  firmado con o sin prefijos. Cambia la forma textual del `rEnviDe`: el `rDE`
  repite `xmlns="http://ekuatia.set.gov.py/sifen/xsd"` antes de
  `xmlns:xsi` (la cabecera habitual de un `rDE` del SIFEN), y un `rDE`
  prefijado conserva su prefijo en lugar de pasar al namespace por defecto.
- El firmador PKCS12 acepta `bytearray` y `memoryview`, además de `bytes`,
  para el contenido del certificado, la contraseña y el documento a firmar.
- El autor declarado en los metadatos del paquete es "The KilaSifen Authors".
- Python 3.10 vuelve a estar soportado como declara `requires-python`: el
  código y los tests usan `timezone.utc` en lugar de `datetime.UTC` (3.11+), y
  `fecha_emision` acepta el sufijo `Z`, que `datetime.fromisoformat` solo
  interpreta desde 3.11. La suite completa pasa con `datetime.UTC` borrado.
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

### Fixed

- Engine: `enviar_lote` arma el lote con el formato oficial (decisión F65).
  Antes unía los `rDE` con saltos de línea, los codificaba en base64 a mano y
  el binding volvía a codificarlos, sin ZIP ni `rLoteDE`: el SIFEN lo tomaba
  como contenido no válido (`0301` o bloqueo del RUC). Ahora `xDE` lleva un
  ZIP con una sola entrada `.xml` que contiene una única declaración UTF-8, la
  raíz `<rLoteDE>` sin namespace y de 1 a 50 `rDE` sin declaración, con su
  `xmlns` y sin nada entre etiquetas, codificado en base64 una sola vez (MT
  v150 §7.2.1, §7.2.2.2, §7.2.4 y §9.2; Guía de mejores prácticas, oct-2024,
  pp. 4, 6-9; XSD `WS_SiRecepLoteDE_v141.xsd`). Antes de enviar valida el
  mismo `iTiDE` y RUC emisor, que no se repitan CDC y el tope de 1000 KB del
  mensaje (Guía p. 6).
- Engine: la espera de lotes trataba `0300` (código de recepción) y `0360`
  (lote inexistente) como pendientes y terminaba en `0361`, el único estado
  realmente pendiente, consultando cada 2 s durante 120 s. Ahora sigue el MT
  v150 (Tabla F, p. 49; §12.3.3) y la Guía (pp. 6, 9 y 10): solo consulta
  tras un `0300` con `dProtConsLote`; `0361` es el único pendiente; `0362`
  devuelve el detalle de cada DE; `0360`, `0363`, `0340` y `0320` son
  errores; con `0364` o pasadas 48 h consulta cada CDC con siConsDE, y las
  consultas van a los 10 minutos y después cada 10 minutos (decisión F66).

- Docker Compose: `worker`, `outbox` y `migrate` deshabilitan el
  `HEALTHCHECK` HTTP (`/v1/health`) que heredaban de la imagen. Ninguno sirve
  HTTP, así que Docker los marcaba `unhealthy` aunque funcionaran. La API lo
  conserva.
- Docker Compose: Redis guarda sus datos con AOF (`appendfsync everysec`) en
  el volumen `kila-redis-data`. Antes un reinicio del contenedor perdía los
  jobs encolados, los leases y el heartbeat del outbox. `docker compose down -v`
  borra también este volumen.
- CI: el job `platform-tests` corre también `tests/domain`, que ningún job
  ejecutaba. `tests/test_deployment_artifacts.py` falla si una carpeta de
  pruebas queda fuera de ese job.
- CI: el workflow corre en los pull requests contra cualquier rama, no solo
  contra `main`. Se mantienen el push a `main` y la corrida semanal.
- CI: el job `docs-site` instala pnpm con `pnpm/action-setup` antes de
  `actions/setup-node`. Con `cache: pnpm`, `setup-node` necesita pnpm ya
  instalado, y el paso `corepack enable` corría después.
- Runbook de Railway (`docs/DEPLOYMENT.md`):
  - agrega el servicio `outbox`, que faltaba aunque `/v1/ready` exige su
    heartbeat en staging y production;
  - el start command del worker va envuelto en `/bin/sh -c "exec ..."`.
    Railway corre en forma exec los start commands de servicios con
    `Dockerfile` y no expande `$KILA_SIFEN_REDIS_URL`. La API deja el start
    command vacío y usa el `CMD` del `Dockerfile`, que ya expande `$PORT`;
  - el healthcheck de Railway pasa de `/v1/ready` a `/v1/health`. Railway lo
    consulta sólo al desplegar y lo da por fallido a los 300 s; con
    `/v1/ready` el primer deploy de la API fallaba siempre, porque worker y
    outbox se crean después;
  - documenta el orden de despliegue (Railway no ordena los deploys por push),
    `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` para API y worker (el default es
    0 s) y la URL `postgresql+psycopg://` armada con las variables `PG*`.
- `.env.example` y el README explican qué proceso lee
  `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` (la API) y
  `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` (el worker) y qué se pierde si quedan
  en su default `false`. El default del código no cambia.
- `docs/operations`: rotación de la clave Fernet y ciclo de vida de jobs
  incluyen el outbox y los interruptores `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` y
  `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS`.

### Security

- Firmador XMLDSig (`kilasifen.engine.sdk.signer`) reescrito desde la
  especificación:
  - rechaza documentos con `DOCTYPE` y parsea sin resolver entidades, sin
    acceso a la red y sin cargar DTD;
  - no modifica el árbol `lxml` que recibe: firma una copia parseada de nuevo;
  - si un ancestro declara un prefijo para el namespace XMLDSig
    (`xmlns:ds`), la `Signature` mantiene su propia declaración por defecto y
    la firma sigue verificando.
- La transmisión ya no escribe en disco la clave privada del emisor sin
  cifrar. El PEM temporal del TLS mutuo pasa a ser PKCS#8 cifrado con una
  contraseña aleatoria por instancia que solo vive en memoria, y se carga con
  `ssl.SSLContext.load_cert_chain` desde un `HTTPAdapter` propio
  (`kilasifen.engine.transmision.conexion`). Si el proceso muere antes de
  borrar el archivo, la clave que queda no se puede usar. La sesión ya no
  usa `Session.cert` y sigue verificando el certificado del servidor.
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
