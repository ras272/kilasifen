# API pública de `kilasifen.engine`

Qué se puede importar del engine fiscal desde código externo y qué garantías
tiene cada parte. La API HTTP de la plataforma está documentada aparte (ver
[Plataforma](#plataforma)).

Versión actual: `0.2.0`, todavía sin publicar en PyPI. Mientras el número de
versión empiece con `0.`, una versión minor puede romper compatibilidad; los
cambios incompatibles se anotan en `CHANGELOG.md` bajo "Breaking changes",
como pasó en 0.2.0 con `TransmissaoDE` y `TransmissaoEvento`, que pasaron a
`TransmisionDE` y `TransmisionEvento`.

## Niveles de estabilidad

| Nivel | Qué abarca | Qué esperar |
| --- | --- | --- |
| Contrato | Los nueve nombres de `kilasifen.engine.__all__` | Quitar o renombrar uno es un breaking change. Lo cubren `tests/test_public_api.py` y un paso del job `build-artifacts` del workflow de CI, que instala el wheel sin extras; ese workflow todavía no completó ninguna ejecución. |
| Fuera del contrato, de uso directo | `kilasifen.engine.transmision`, `kilasifen.engine.firma`, `kilasifen.engine.binding` y `kilasifen.engine.sdk` con sus submódulos | Se pueden importar, pero pueden cambiar en cualquier versión minor. |
| Generado | `kilasifen.engine.de.bindings.v150.*` | Lo produce `scripts/generate_bindings.py`. Clases y campos siguen a los XSD de la SET y pueden cambiar al regenerar o con XSD nuevos. |
| Interno | Todo nombre que empieza con guion bajo, en cualquier módulo | Sin garantía. Puede cambiar en cualquier commit. |

## El contrato: `kilasifen.engine`

| Nombre | Tipo | Uso | Definido en |
| --- | --- | --- | --- |
| `__version__` | `str` | Versión del paquete; es el mismo valor que `kilasifen.__version__`. | `kilasifen/__init__.py` |
| `sign_xml(xml_input, pkcs12_data, pkcs12_password, doc_id)` | función | Firma XMLDSig enveloped (RSA-SHA256, canonicalización exclusiva, digest SHA-256) del nodo cuyo `Id` es `doc_id`. Devuelve el XML firmado como `str`. | `kilasifen/engine/firma.py` |
| `PRODUCCION`, `TEST` | `int` (`1` y `2`) | Ambientes del SIFEN. | `kilasifen/engine/transmision/config.py` |
| `ENDPOINTS` | `dict[int, dict[str, str]]` | URL de cada servicio, agrupadas por ambiente. | `kilasifen/engine/transmision/config.py` |
| `get_endpoint(ambiente, servicio)` | función | URL de un servicio. Lanza `ValueError` si el ambiente o el servicio no existen. | `kilasifen/engine/transmision/config.py` |
| `TransmisionDE` | clase | Envío de documentos electrónicos. | `kilasifen/engine/transmision/de.py` |
| `ConsultaSIFEN` | clase | Consultas de DE, lote, RUC y DTE. | `kilasifen/engine/transmision/consulta.py` |
| `TransmisionEvento` | clase | Envío de eventos. | `kilasifen/engine/transmision/evento.py` |

Servicios válidos para `get_endpoint`: `recep_de`, `recep_lote`, `cons_de`,
`cons_lote`, `cons_ruc`, `evento`, `cons_dte` y `cons_dte_async`. Los dos
últimos son experimentales y están listados en
`kilasifen.engine.transmision.config.SERVICIOS_EXPERIMENTALES`: la SET publica
los XSD de la consulta DTE, pero su dirección, sus códigos y sus plazos no
figuran en el Manual Técnico v150 (§7.10), en las notas técnicas 01 a 27, en la
Guía de mejores prácticas ni en la FAQ de la DNIT.

### Clases de transmisión

Las tres heredan de `TransmisionBase` (`kilasifen.engine.transmision.base`,
que la fachada no reexporta) y comparten el constructor:

```python
TransmisionDE(
    ambiente,             # PRODUCCION o TEST
    pkcs12_data,          # contenido del .pfx/.p12 del emisor
    pkcs12_password,      # str, bytes o None
    timeout=30.0,         # segundos por cada POST
    max_retries=0,        # reintentos por envío (ver "Errores de transporte"); negativo -> ValueError
    retry_backoff=0.2,    # base, en segundos, de la espera exponencial
)
```

Construir una instancia no toca disco, red ni certificado: los archivos PEM
temporales, el transporte HTTP con TLS mutuo y los clientes SOAP se crean en
el primer uso. Se liberan con `close()` (o su sinónimo `cleanup()`) o al salir
de un bloque `with`. Una instancia no debe compartirse entre hilos.

La clave privada se escribe como PKCS#8 cifrado con una contraseña aleatoria
propia de la instancia, que solo vive en memoria; si el proceso muere antes de
borrar el archivo, lo que queda en disco no sirve sin ella. El certificado y la
clave se cargan en un `ssl.SSLContext` propio
(`kilasifen.engine.transmision.conexion`) que la sesión `requests` usa para
`https://`, con la verificación del certificado del servidor activada.

| Clase | Método | Qué hace |
| --- | --- | --- |
| `TransmisionDE` | `enviar_de_xml(xml_de)` | Envía un `rDE` ya firmado sin pasarlo por xsdata: lo parsea con lxml, le agrega `xsi:schemaLocation` si no lo tiene y lo inserta en `rEnviDe` como texto, con sus propias declaraciones de namespace y sus prefijos, para que la firma siga verificando. Es el camino que usa la plataforma. |
| `TransmisionDE` | `enviar_de(rde, sign=True)` | Serializa un binding `RDe` con el namespace del SIFEN por defecto (sin prefijos), lo firma con el `Id` de su `DE` y lo envía como `enviar_de_xml`. El binding tiene el layout v141 (ver [Bindings generados](#bindings-generados)). |
| `TransmisionDE` | `enviar_lote_xml(lista_xml, lote_id=None)` | Envía en un lote asíncrono de 1 a 50 `rDE` (`MAX_LOTE`) ya firmados, sin volver a firmarlos. Ver [Lote asíncrono](#lote-asíncrono). |
| `TransmisionDE` | `enviar_lote(lista_rde, lote_id=None, sign=True)` | Serializa y firma cada binding con el `Id` de su `DE` y sigue el camino de `enviar_lote_xml`. |
| `ConsultaSIFEN` | `consultar_de(cdc)` | Consulta un DE por CDC; exige 44 dígitos ASCII. |
| `ConsultaSIFEN` | `consultar_lote(prot_lote=None, *, cdc=None)` | Estado de un lote por su número (`dProtConsLote`) o, si ese número no llegó, por un CDC del lote (`dCDC`). Exige exactamente uno de los dos. |
| `ConsultaSIFEN` | `consultar_ruc(ruc)` | Datos de un contribuyente; acepta espacios y la forma `RUC-DV`. |
| `ConsultaSIFEN` | `consultar_dte(consulta_dte)` | Consulta DTE sincrónica. **Experimental**: emite `SifenExperimentalWarning`. |
| `ConsultaSIFEN` | `consultar_dte_async(consulta_dte_async)` | Registra una consulta DTE asíncrona; la respuesta trae el protocolo. **Experimental**: emite `SifenExperimentalWarning`. |
| `TransmisionEvento` | `enviar_evento(evento)` | Envía un `gGroupGesEve` dentro de `rEnviEventoDe`. No firma: el evento tiene que llegar firmado si corresponde, y como xsdata lo vuelve a serializar, una firma hecha sobre otro texto puede dejar de verificar. |

Las respuestas son instancias de los bindings de cada servicio (por ejemplo,
`RRetEnviDe` para `enviar_de_xml`).

### Lote asíncrono

`enviar_lote_xml` y `enviar_lote` arman el `xDE` de `rEnvioLote` según el
Manual Técnico v150 (§7.2.1, §7.2.2.2, §7.2.4 y §9.2) y la Guía de mejores
prácticas de la DNIT (octubre de 2024, pp. 6-9):

- un ZIP con una sola entrada, `lote.xml` (`NOMBRE_ARCHIVO_LOTE`), que
  contiene una única declaración `<?xml version="1.0" encoding="UTF-8"?>`, la
  raíz `<rLoteDE>` sin namespace y los `rDE` concatenados sin nada entre
  ellos;
- cada `rDE` sin declaración propia, con su `xmlns` y con
  `xsi:schemaLocation` (se agrega si falta, como en el envío sincrónico);
- el binding codifica el ZIP en base64 una sola vez al serializar.

Antes de enviar, y sin tocar la red, se lanza `ValueError` si el lote tiene
0 o más de 50 documentos, mezcla tipos de DE (`iTiDE`) o RUC emisores
(`dRucEm`), repite un CDC, trae un `rDE` sin `DE/@Id`, `iTiDE` o `dRucEm`,
tiene blancos entre etiquetas (no se quitan porque romperían la firma) o si
el sobre SOAP supera `MAX_BYTES_MENSAJE_LOTE` (1.000.000 bytes). El SIFEN
rechaza esos lotes con `0301` o bloquea el RUC de 10 a 60 minutos.

La respuesta `rResEnviLoteDe` trae `0300` y el número de lote
(`dProtConsLote`) o `0301` (lote no encolado). Para esperar el resultado,
`kilasifen.engine.sdk.polling` ofrece:

| Nombre | Qué hace |
| --- | --- |
| `require_lote_protocol(recepcion)` | Devuelve `dProtConsLote` de una recepción `0300`. Lanza `SifenRejectionError` con cualquier otro código y `SifenLoteError` si falta el número. |
| `classify_lote_response(respuesta)` | `"pending"` (`0361`), `"concluded"` (`0362`) o `"expired"` (`0364`). Lanza `SifenLoteError` con `0360`, `0363`, `0340`, `0320` o un código no documentado. |
| `lote_document_results(respuesta)` | Un `LoteDocumentResult` por cada `gResProcLote` de un `0362`, con `status` `approved`, `approved_with_observation`, `rejected` o `unknown` (`dEstRes` comparado sin tildes ni mayúsculas), `messages` y `protocol` (`dProtAut`). |
| `consulta_de_result(cdc, respuesta)` | Clasifica una respuesta de siConsDE: `found` (`0422`), `not_found_or_not_approved` (`0420`) o `error`. |
| `poll_lote_status(consultar_lote, prot_lote, config, *, cdcs, consultar_de, seconds_since_reception, clock, sleep)` | Bucle bloqueante: espera `config.initial_delay_seconds` desde la recepción, consulta cada `config.interval_seconds` mientras siga en `0361` y devuelve un `LoteResult` `"concluded"`. Con `0364`, o pasadas 48 h desde la recepción, consulta cada CDC con `consultar_de` y devuelve un `LoteResult` `"expired"`. |

`PollingConfig()` usa por defecto 600 s antes de la primera consulta, 600 s
entre consultas, 48 h de espera máxima y ningún tope de intentos.
`SifenClient.enviar_lote_y_esperar` combina el envío, `require_lote_protocol`
y `poll_lote_status` con los CDC del lote. El procesamiento puede tardar de 1
a 24 horas: un servicio debería programar cada consulta como un job en lugar
de bloquear un proceso.

### Errores de transporte

Todas las fallas de transporte heredan de `SifenTransportError`
(`kilasifen.engine.sdk.errors`, reexportadas en `kilasifen.engine.sdk`):

| Excepción | Cuándo | ¿El SIFEN pudo recibir la solicitud? |
| --- | --- | --- |
| `SifenRequestNotSentError` | No se resolvió el nombre del servidor, la conexión fue rechazada o el destino era inalcanzable, se agotó el tiempo al conectar o falló el handshake TLS. | No: es seguro volver a enviar. |
| `SifenTimeoutError` | Se agotó el tiempo esperando la respuesta (incluye el timeout de lectura). | Sí: resultado incierto. |
| `SifenUnexpectedResponseError` | La respuesta no es la de la operación: SOAP Fault (`actual_root == "Fault"`), sobre de otra operación, HTML de un proxy, cuerpo que no es XML (`"invalid_xml"`) o XML que el binding no acepta. Trae `expected_root`, `actual_root`, `code`, `response_message` y `raw_body` (comienzo del cuerpo, hasta 4096 caracteres; no forma parte del mensaje). | Sí: resultado incierto. |
| `SifenTransportError` | Cualquier otro fallo: conexión cortada a mitad de la respuesta, error HTTP sin cuerpo XML, etc. | Sí: resultado incierto. |

El handshake TLS se reconoce porque los sockets del contexto de
`kilasifen.engine.transmision.conexion` marcan los errores ocurridos durante
el handshake; un fallo que llega desde `requests` como `ReadTimeout` o
`SSLError` solo se clasifica como no enviado si tiene esa marca. Ante un
resultado incierto, consultar por CDC antes de volver a transmitir.

Política de reintentos (`max_retries` intentos adicionales, con espera
`retry_backoff * 2**i`):

| Clase | Reintenta `SifenRequestNotSentError` | Reintenta timeouts, cortes y 5xx sin cuerpo XML |
| --- | --- | --- |
| `TransmisionDE` (`enviar_de`, `enviar_de_xml`, `enviar_lote`, `enviar_lote_xml`) | Sí | No: el error sale en el primer intento |
| `TransmisionEvento` (`enviar_evento` y el envío crudo) | Sí | No: el error sale en el primer intento |
| `ConsultaSIFEN` | Sí | Sí |

Ninguna clase reintenta un 4xx ni un error de `requests` que no sea de red.
`SifenClient` sigue creando `TransmisionDE` y `TransmisionEvento` con
`max_retries=0`.

## Dependencias opcionales

`import kilasifen.engine` solo necesita `xsdata`. Lo demás se importa al
usarse. Si falta una dependencia, `sign_xml` y las operaciones de transmisión
que no firman lanzan un `ImportError` que dice qué extra instalar. Hay caminos
sin ese aviso: `BindingMixin.validate_xml` deja pasar el `ImportError`
genérico de `lxml`, y la firma dentro de `enviar_de`/`enviar_lote` o con
`kilasifen.engine.sdk.signer` informa la falta como `SifenSignatureError`.

| Extra | Habilita |
| --- | --- |
| `sign` | `sign_xml`, `BindingMixin.sign_xml` y `BindingMixin.validate_xml` (este último necesita `lxml`) |
| `transmision` | Envíos y consultas de `TransmisionDE`, `ConsultaSIFEN` y `TransmisionEvento` |
| `soap` | Solo el cliente SOAP de xsdata |

`kilasifen.engine.sdk.validation` es la excepción: importa `lxml` al cargarse,
así que importarlo directamente requiere `sign` o `transmision`.

## Fuera del contrato

Estos módulos se pueden usar directamente, sabiendo que pueden cambiar sin
pasar por la fachada:

- `kilasifen.engine.transmision`: exporta los siete nombres de transmisión de
  la fachada (todos menos `__version__` y `sign_xml`). `TransmisionBase` está
  en el submódulo `base`; `MAX_LOTE`, `MAX_BYTES_MENSAJE_LOTE` y
  `NOMBRE_ARCHIVO_LOTE`, en `de`, y `SERVICIOS_EXPERIMENTALES`, en `config`.
- `kilasifen.engine.firma`: `sign_xml`.
- `kilasifen.engine.binding`: `BindingMixin`, la clase base de todas las
  dataclasses generadas.
- `kilasifen.engine.sdk`: `SifenClient` (fachada que combina envío, consultas,
  eventos, polling, CDC, QR y KuDE), las excepciones `Sifen*Error` (salvo
  `SifenRejectionError`, que solo está en `sdk.errors`), entre ellas
  `SifenLoteError` y el aviso `SifenExperimentalWarning`, los helpers
  fiscales (`generate_cdc`, `calculate_mod11_dv`, `build_qr_payload`,
  `generate_dcarqr` y sus variantes), la espera de lotes (`PollingConfig`,
  `LoteResult`, `LoteDocumentResult` y las funciones de la sección
  [Lote asíncrono](#lote-asíncrono)), la espera experimental de la consulta
  DTE asíncrona (`poll_dte_async_status`, sin textos de "pendiente" por
  defecto) y el render HTML del KuDE. Los submódulos `signer` (`get_pkcs12_signer`) y
  `validation` (`validate_xml`) no se reexportan desde `kilasifen.engine.sdk`.

### Bindings generados

`scripts/generate_bindings.py` procesa los XSD en orden alfabético y ubica
cada clase en el módulo del XSD donde quedó definida. Varios XSD redefinen
los mismos tipos y xsdata conserva solo la última definición, así que no todo
XSD tiene módulo propio: hoy son 26 módulos para 47 XSD. Las clases van en
PascalCase y los campos llevan el nombre exacto del XSD (`dNumTim`,
`gCamItem`). Cada dataclass hereda de `BindingMixin`; los tipos enumerados se
generan como `Enum`. Para revisar que los bindings versionados coinciden con
los XSD sin escribir nada: `python scripts/generate_bindings.py --check`
(necesita `xsdata[cli]==26.2`, que no forma parte de ningún extra).

Limitación conocida: el único `RDe` generado sale de `FE_v141.xsd`
(`kilasifen.engine.de.bindings.v150.fe_v141.RDe`) y tiene la estructura v141,
sin `dSisFact`. Sirve para leer y escribir las muestras, pero la plataforma no
lo usa para emitir: arma el XML con
`kilasifen/infrastructure/sifen/typed_xml_builder.py` y lo valida contra
`siRecepDE_v150.xsd` antes de firmar (ignora los errores sobre `Signature` y
uno causado por un defecto del XSD en `dEntCont`).

## Qué usa hoy la plataforma

La plataforma no se limita al contrato. Esta es la lista completa de lo que
importa del engine (rutas relativas a `kilasifen/`):

| Origen | Qué usa | Dónde |
| --- | --- | --- |
| Contrato | `PRODUCCION`, `TEST`, `sign_xml`, `ConsultaSIFEN`, `TransmisionDE` | `infrastructure/sifen/engine.py`, `infrastructure/sifen/event.py`, `infrastructure/sifen/query.py` |
| Fuera del contrato | `TransmisionEvento` (desde `kilasifen.engine.transmision.evento`) | `infrastructure/sifen/event.py` |
| Fuera del contrato | Excepciones de `kilasifen.engine.sdk.errors` | `infrastructure/sifen/` (la clasificación enviado/no enviado vive en `application/sifen_submissions.py`), `infrastructure/jobs/workers.py`, `infrastructure/kude/`, `infrastructure/sandbox/transport.py`, `application/events/service.py`, `application/events/attempts.py` |
| Fuera del contrato | `get_pkcs12_signer`, `validate_xml`, `generate_cdc`, `calculate_mod11_dv` | `infrastructure/sifen/typed_event_builder.py`, `infrastructure/sifen/typed_xml_builder.py` |
| Generado | `ws_si_cons_de_v141`, `ws_si_cons_ruc_v141`, `ws_si_recep_de_v150.RRetEnviDe`, `evento_v150.TgGroupGesEve`, `ws_si_recep_evento_v150.REnviEventoDe` | `infrastructure/sifen/engine.py`, `infrastructure/sifen/query.py`, `infrastructure/sifen/typed_event_builder.py` |
| **Interno** | `_build_enviar_de_request_xml` (de `kilasifen.engine.transmision.de`) y `_generate_id` (de `kilasifen.engine.transmision.base`) | `infrastructure/sifen/engine.py`: arma, antes de enviar, el `rEnviDe` con el `dId` real; la plataforma lo guarda con el documento y envía exactamente ese texto |
| **Interno** | `TransmisionDE._send_raw_xml("recep_de", ...)` y `TransmisionDE._como_respuesta(..., RRetEnviDe)` | `infrastructure/sifen/engine.py`: envía el `rEnviDe` guardado sin reconstruirlo y lee la respuesta (una respuesta inesperada llega como `SifenUnexpectedResponseError`) |
| **Interno** | `_generate_id` (de `kilasifen.engine.transmision.evento`) | `infrastructure/sifen/event.py`: genera el `dId` del envío de eventos |
| **Interno** | `TransmisionEvento._send_raw_xml("evento", ...)` | `infrastructure/sifen/event.py`: envía el `rEnviEventoDe` como texto para no alterar la firma |

Las filas **Interno** son dependencias de la plataforma sobre detalles
privados del engine. Cualquier cambio en esos nombres o en su comportamiento
rompe la emisión o los eventos aunque el contrato siga intacto. Hasta que se
publiquen como API, un cambio en ellos tiene que ir junto con el ajuste en
`kilasifen/infrastructure/sifen/` y sus tests.

## Problemas conocidos

Defectos que la reescritura de 0.2.0 conservó a propósito para mantener el
comportamiento anterior. Están pendientes de corrección:

- La consulta DTE (`consultar_dte`, `consultar_dte_async` y
  `poll_dte_async_status`) es experimental: sus rutas, códigos y mensajes no
  están documentados por la SET.
- `SifenClient` pasa su `max_retries` (por defecto `2`) a `ConsultaSIFEN`, y
  eso incluye `consultar_dte_async`, que registra una consulta nueva en el
  SIFEN: ante un timeout se reintenta como si fuera una consulta de solo
  lectura.

## Ejemplos

Firmar y enviar un DE en el ambiente de pruebas:

```python
from pathlib import Path

from kilasifen.engine import TEST, TransmisionDE, sign_xml

# xml_rde: texto del rDE, preferentemente con el namespace del SIFEN por
# defecto y sin prefijos (la forma que usa la plataforma); cdc: el Id de su
# elemento DE.
pfx = Path("emisor.pfx").read_bytes()
xml_firmado = sign_xml(xml_rde, pfx, clave_pfx, doc_id=cdc)

with TransmisionDE(ambiente=TEST, pkcs12_data=pfx, pkcs12_password=clave_pfx) as envio:
    respuesta = envio.enviar_de_xml(xml_firmado)
```

Consultar un documento por CDC:

```python
from kilasifen.engine import TEST, ConsultaSIFEN

with ConsultaSIFEN(ambiente=TEST, pkcs12_data=pfx, pkcs12_password=clave_pfx) as consulta:
    respuesta = consulta.consultar_de(cdc)
```

Resolver una URL sin conectarse:

```python
from kilasifen.engine import PRODUCCION, get_endpoint

url = get_endpoint(PRODUCCION, "cons_ruc")
```

## Plataforma

Este documento cubre solo el engine. Para la plataforma:

- `docs/architecture/kila-api-contract.md`: contrato HTTP para los ERP.
- `docs/architecture/kila-platform.md`: arquitectura de la plataforma.
- `docs/operations/deployment-compose.md`: stack local con Docker Compose
  (para desarrollo, no para producción).
