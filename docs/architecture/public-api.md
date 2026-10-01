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
`cons_lote`, `cons_ruc`, `evento`, `cons_dte` y `cons_dte_async`.

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
| `TransmisionDE` | `enviar_lote(lista_rde, lote_id=None, sign=True)` | Arma un lote asíncrono de hasta 50 documentos (`MAX_LOTE`). Ver [problemas conocidos](#problemas-conocidos). |
| `ConsultaSIFEN` | `consultar_de(cdc)` | Consulta un DE por CDC; exige 44 dígitos ASCII. |
| `ConsultaSIFEN` | `consultar_lote(prot_lote)` | Estado de un lote por número de protocolo. |
| `ConsultaSIFEN` | `consultar_ruc(ruc)` | Datos de un contribuyente; acepta espacios y la forma `RUC-DV`. |
| `ConsultaSIFEN` | `consultar_dte(consulta_dte)` | Consulta DTE sincrónica. |
| `ConsultaSIFEN` | `consultar_dte_async(consulta_dte_async)` | Registra una consulta DTE asíncrona; la respuesta trae el protocolo. |
| `TransmisionEvento` | `enviar_evento(evento)` | Envía un `gGroupGesEve` dentro de `rEnviEventoDe`. No firma: el evento tiene que llegar firmado si corresponde, y como xsdata lo vuelve a serializar, una firma hecha sobre otro texto puede dejar de verificar. |

Las respuestas son instancias de los bindings de cada servicio (por ejemplo,
`RRetEnviDe` para `enviar_de_xml`).

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
| `TransmisionDE` (`enviar_de`, `enviar_de_xml`, `enviar_lote`) | Sí | No: el error sale en el primer intento |
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
  la fachada (todos menos `__version__` y `sign_xml`). `TransmisionBase` y
  `MAX_LOTE` están en sus submódulos `base` y `de`.
- `kilasifen.engine.firma`: `sign_xml`.
- `kilasifen.engine.binding`: `BindingMixin`, la clase base de todas las
  dataclasses generadas.
- `kilasifen.engine.sdk`: `SifenClient` (fachada que combina envío, consultas,
  eventos, polling, CDC, QR y KuDE), las excepciones `Sifen*Error` (salvo
  `SifenRejectionError`, que solo está en `sdk.errors`), los helpers
  fiscales (`generate_cdc`, `calculate_mod11_dv`, `build_qr_payload`,
  `generate_dcarqr` y sus variantes), el polling de lotes y DTE asíncronos y
  el render HTML del KuDE. Los submódulos `signer` (`get_pkcs12_signer`) y
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

- `enviar_lote` codifica el contenido en base64 dos veces y no lo comprime en
  ZIP, así que no respeta el formato del servicio de lotes. La plataforma no
  lo usa.
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
