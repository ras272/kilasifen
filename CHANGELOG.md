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
  a quien implemente motores o transportes propios para los workers.
- Plataforma: `EventSubmissionGateway.submit_event` se reemplaza por
  `prepare_event` y `submit_prepared(request_xml=...)`; aparece
  `PreparedEventSubmission` y `EventSubmissionOutcome` deja de llevar
  `generated_xml`, `signed_xml` y `request_xml`.
  `EventService.process_queued_event` se reemplaza por
  `begin_queued_event_attempt` y `record_event_attempt`, que el worker llama
  en transacciones separadas.

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
  segunda relee documento y job con `FOR UPDATE` y registra el resultado sin
  pisar un estado terminal escrito mientras tanto. Antes todo el job era una
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
  incierto: `retry_pending` y reconciliación por CDC. Ninguna excepción escapa
  del worker sin registrarse. Un intento incierto que agota el presupuesto
  pasa a `reconciliation_required` (antes podía quedar `failed` y un
  reintento manual lo reenviaba). Un documento que quedó en `submitting`
  porque el worker murió se reconcilia por CDC en el intento siguiente.
- Plataforma: los eventos (cancelación e inutilización) siguen el mismo
  esquema de dos transacciones. El worker guarda el grupo firmado
  (`signed_xml`, antes vacío) y el `rEnviEventoDe` exacto con el evento en
  `submitting` antes de enviarlo, y registra el resultado en una segunda
  transacción, sin retener el bloqueo del emisor durante la llamada. Un
  request que no salió deja el evento en `queued` (`transport_not_sent`);
  cualquier otro fallo, en `retry_pending` (`transport`). Una respuesta de
  eventos que no es `rRetEnviEventoDe` (SOAP Fault, HTML, cuerpo truncado)
  ahora es `SifenUnexpectedResponseError`, resultado incierto, y ya no un
  error de validación que marcaba el evento como `failed`. El reintento de
  un evento incierto sigue reenviándolo, como antes.
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
- `tests/conftest.py` usa `timezone.utc` en vez de `datetime.UTC`, que no
  existe en Python 3.10, la versión más baja de la matriz de CI. Eso solo no
  alcanza para que el job del engine (`pytest tests/test_*.py`) pase en 3.10:
  `tests/test_logging.py` y `tests/test_observability.py` importan la
  plataforma, que usa `datetime.UTC` en 18 módulos y en la práctica necesita
  Python 3.11 o posterior.

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
- `SECURITY.md` deja un solo canal para reportar vulnerabilidades: el
  private vulnerability reporting de GitHub. Se quitó el correo del mantenedor
  anterior, que figuraba como segunda opción.

### Documentation

- Matriz de trazabilidad normativa en `docs/normativa/matriz.md`.
- Documentos de contribución y de política de seguridad.
- README, `CLAUDE.md` y la guía de API pública reescritos desde cero contra
  el código actual, con sus limitaciones conocidas.

## [0.1.1] - 2026-04-22

### Added

- stable top-level public API facade.

### Changed

- README normalization and public API documentation updates.
