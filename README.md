# KilaSifen

KilaSifen conecta sistemas de gestión (ERP, puntos de venta, comercios en
línea) con el **SIFEN**, el sistema de facturación electrónica de la SET de
Paraguay. El repositorio tiene dos capas:

1. **Una API HTTP headless** (FastAPI + PostgreSQL + Redis/RQ + outbox). El
   sistema integrador manda la operación en JSON y la plataforma se ocupa del
   resto: numeración, XML v150, firma, transmisión, reintentos,
   reconciliación, KuDE y webhooks.
2. **Un motor Python, `kilasifen.engine`**: clases generadas desde los XSD
   oficiales, firma XMLDSig y cliente SOAP con mTLS. La API está construida
   sobre él y también se puede usar por separado como librería.

Si integrás un ERP, lo habitual es consumir la API y no escribir Python. El
motor sirve cuando necesitás leer, validar, firmar o transmitir XML del SIFEN
desde tu propio código.

## Estado del proyecto

- **Alpha, versión 0.2.0.** La API Python del motor todavía puede cambiar. El
  contrato HTTP `/v1` solo admite cambios aditivos (ver
  [`docs/INTEGRATION.md`](docs/INTEGRATION.md)).
- **Sin publicar.** El paquete Python no está en PyPI y el SDK TypeScript no
  está en npm; ambos se instalan desde este repositorio.
- **CI sin resultados todavía.** El workflow `.github/workflows/tests.yml` está
  definido, pero ninguna ejecución llegó a completarse. Hasta que eso cambie, la
  referencia es correr las pruebas en local.
- **Python.** El motor funciona con 3.10 o superior. La plataforma usa
  `datetime.UTC`, así que en la práctica requiere **3.11+**, aunque
  `pyproject.toml` declare `>=3.10`.
- **Código reescrito desde cero.** El motor se reescribió en modalidad
  clean-room y conserva a propósito el comportamiento anterior, defectos
  incluidos. Esos defectos se van a corregir en commits posteriores y están
  detallados en [Limitaciones conocidas](#limitaciones-conocidas).

## Mapa del repositorio

| Ruta | Contenido |
| --- | --- |
| `kilasifen/api`, `application`, `domain`, `infrastructure`, `repositories`, `admin` | Plataforma: rutas HTTP, casos de uso, modelos, workers, outbox y persistencia |
| `kilasifen/engine` | Motor: bindings, firma, transmisión y utilidades fiscales |
| `kilasifen/engine/de/schemas/v150` | Esquemas XSD publicados por la SET |
| `kilasifen/engine/de/bindings/v150` | Clases generadas a partir de esos XSD (no se editan a mano) |
| `kilasifen/engine/de/samples/v150` | Cinco XML de muestra con datos ficticios |
| `alembic/` | Migraciones de PostgreSQL |
| `apps/docs` | Portal de integración (Next.js + Fumadocs) con la referencia OpenAPI |
| `sdks/typescript` | SDK TypeScript `@kilasifen/sdk` para la API HTTP |
| `scripts/` | Generación de bindings, exportación del OpenAPI y vista previa de KuDE |
| `docs/` | Contrato de integración, runbooks, decisiones de arquitectura y normativa |
| `tests/` | Pruebas del motor y de la plataforma (pytest) |

## La plataforma (API HTTP)

### Funcionalidades actuales

- Emisión con contratos tipados de **factura electrónica**, **nota de crédito**
  y **nota de débito** (`POST /v1/emitters/{emitter_id}/documents/facturas`,
  `.../notas-credito` y `.../notas-debito`). El servidor asigna el número
  fiscal de forma atómica y arma el XML; el cliente nunca lo envía.
- Procesamiento asíncrono: la respuesta inicial deja el documento en `queued`
  y un worker lo firma y lo transmite. El worker confirma en la base el XML
  firmado, el request exacto y el CDC antes de llamar al SIFEN y no retiene
  transacciones ni bloqueos mientras espera la respuesta. El resultado se
  recibe por webhook o consultando el documento o el job.
- Idempotencia con `idempotency_key`: repetir la misma intención devuelve el
  mismo documento.
- Eventos de **cancelación** e **inutilización**.
- Consulta de RUC, consulta del estado de un documento y reconciliación
  explícita sin volver a transmitir un DE cuyo resultado quedó incierto.
- Descarga del XML firmado, KuDE en PDF y datos del KuDE en JSON.
- Webhooks firmados con HMAC, con reintentos y defensa contra SSRF.
- Varios consumidores aislados: cada API key ve solo los emisores de su
  consumidor, y los certificados, contraseñas y CSC se guardan cifrados.
- Sandbox determinista: solo con `KILA_SIFEN_ENVIRONMENT=test`, el encabezado
  `X-Kila-Test-Outcome` fuerza resultados reproducibles (aprobado, rechazado,
  timeout, respuesta perdida…).

### Arranque local con Docker Compose

Compose está pensado para desarrollo y no reemplaza una receta de producción.
Requiere Docker con el plugin Compose.

```bash
cp .env.example .env
```

Completá en `.env` estos valores (el archivo de ejemplo los deja vacíos a
propósito):

| Variable | Qué poner |
| --- | --- |
| `POSTGRES_PASSWORD` | Una contraseña local cualquiera |
| `KILA_SIFEN_DATABASE_URL` | `postgresql+psycopg://kilasifen:<POSTGRES_PASSWORD>@postgres:5432/kilasifen` |
| `KILA_SIFEN_ENCRYPTION_KEY` | Una clave Fernet |
| `KILA_SIFEN_API_KEYS` | Arreglo JSON con la clave de administración inicial, por ejemplo `["<clave>"]` |

Para generar la clave de administración y la clave Fernet:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Después:

```bash
docker compose config --quiet
docker compose up -d --build
curl http://127.0.0.1:8000/v1/health   # el proceso responde
curl http://127.0.0.1:8000/v1/ready    # PostgreSQL y Redis (workers: solo en staging/production)
```

Compose levanta PostgreSQL, Redis (con AOF en un volumen, así que los jobs
encolados sobreviven a un reinicio), un paso de migración
(`alembic upgrade head`), la API en `127.0.0.1:8000`, el worker RQ (colas
`documents`, `events` y `webhooks`) y el despachador del outbox. Sólo la API
conserva el healthcheck HTTP de la imagen; worker, outbox y migración no sirven
HTTP y lo tienen deshabilitado. Todo queda publicado solo en loopback. Con `.env.example` el SIFEN apunta al ambiente de
pruebas. Para apuntar a producción (`KILA_SIFEN_SIFEN_ENVIRONMENT=production`)
la configuración exige además `KILA_SIFEN_ENVIRONMENT=production` y
`KILA_SIFEN_ENABLE_PRODUCTION=true`; si falta alguna, la configuración se
rechaza al iniciar.

`.env.example` deja en `true` `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` (lo lee la
API) y `KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` (lo lee el worker). Mantenelos
así. En el código ambos valen `false` por defecto y ninguna validación los
exige: sin el primero los documentos quedan en `queued` y nunca se emiten; sin
el segundo no se publican webhooks de documentos.

Con la clave de administración se crean el consumidor, su credencial y el
emisor (ver `docs/INTEGRATION.md`). La carga de certificado y timbrado está en
la guía `apps/docs/content/docs/certificados-y-timbrado.mdx` del portal.

### Documentación para integrar

- [`docs/INTEGRATION.md`](docs/INTEGRATION.md): contrato v1 (autenticación y
  scopes, formato de errores, payloads, estados, reconciliación y sandbox).
- [`apps/docs`](apps/docs): portal con guías paso a paso y la referencia HTTP
  generada desde `apps/docs/public/openapi.json`. Requiere Node 22+ y pnpm:
  `cd apps/docs && pnpm install --frozen-lockfile && pnpm dev`.
- [`docs/integrations/webhooks.md`](docs/integrations/webhooks.md): firma,
  verificación y reintentos de webhooks.
- [`docs/operations/deployment-compose.md`](docs/operations/deployment-compose.md):
  detalles del stack local, incluido el worker en Windows sin contenedores.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): runbook de un staging
  independiente (Railway): servicios `api`, `worker` y `outbox`, migración
  como pre-deploy de la API, start commands, healthcheck, orden de despliegue,
  variables obligatorias, red y rollback.
- [`sdks/typescript`](sdks/typescript): cliente TypeScript de la API. Como no
  está publicado en npm, se compila desde esa carpeta (`pnpm install && pnpm build`).

## El motor Python (`kilasifen.engine`)

### Instalación

Como el paquete no está en PyPI, se instala desde una copia del repositorio:

```bash
git clone https://github.com/ras272/kilasifen.git
cd kilasifen
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[sign]"           # elegí los extras según lo que vayas a usar
```

| Extra | Agrega | Para qué |
| --- | --- | --- |
| *(ninguno)* | `xsdata` | Leer, construir y serializar bindings |
| `sign` | `signxml>=5.1`, `cryptography`, `lxml` | Firmar y validar contra los XSD |
| `soap` | `xsdata[soap]` | Cliente SOAP genérico de xsdata, sin firma ni mTLS |
| `transmision` | `xsdata[soap]`, `signxml`, `cryptography`, `requests`, `lxml` | Enviar y consultar al SIFEN con mTLS |
| `platform` | FastAPI, SQLAlchemy, Alembic, RQ, psycopg y otros | Correr la API (junto con `transmision`) |
| `test` | pytest, ruff, mypy y las dependencias de la plataforma | Desarrollo |

`import kilasifen.engine` funciona sin ningún extra: las dependencias pesadas
se cargan recién cuando firmás, validás o transmitís. Si falta el extra de
firma, `sign_xml` lanza un `ImportError` que indica qué instalar.

La fachada estable reúne lo más usado:

```python
from kilasifen.engine import (
    ENDPOINTS,          # URL de cada servicio, por ambiente
    PRODUCCION,         # 1
    TEST,               # 2
    ConsultaSIFEN,
    TransmisionDE,
    TransmisionEvento,
    get_endpoint,       # get_endpoint(TEST, "recep_de") -> URL
    sign_xml,
)
```

### Leer y escribir un DE

Los bindings viven en `kilasifen.engine.de.bindings.v150`, en módulos que
llevan el nombre del XSD de origen (`fe_v141`, `ws_si_recep_de_v150`…). Cuando
varios XSD definen el mismo tipo, la clase queda en un solo módulo, así que hay
menos módulos (26) que esquemas (47). Los atributos conservan el nombre de la
etiqueta del Manual Técnico (`dRucEm`, `iTiDE`, `gCamItem`…). Todas las clases
heredan de
`kilasifen.engine.binding.BindingMixin`, que agrega `from_xml`, `from_path`,
`to_xml`, `validate_xml` y `sign_xml`. El elemento raíz `rDE` corresponde a
`RDe`, en el módulo `fe_v141` (ver [Limitaciones conocidas](#limitaciones-conocidas)).

```python
from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

rde = RDe.from_path("kilasifen/engine/de/samples/v150/factura_electronica.xml")

de = rde.DE
print(de.Id)                            # CDC de 44 dígitos
print(de.gTimb.iTiDE, de.gTimb.dNumTim) # tipo de documento y timbrado
print(de.gDatGralOpe.gEmis.dNomEmi)     # razón social del emisor
print(de.gDatGralOpe.gDatRec.dNomRec)   # nombre del receptor
print(de.gTotSub.dTotGralOpe)           # total de la operación (Decimal)
print(len(de.gDtipDE.gCamItem))         # líneas de detalle

legible = rde.to_xml()                  # con sangría de dos espacios
compacto = rde.to_xml(pretty_print=False)
assert RDe.from_xml(compacto).DE.Id == de.Id
```

Las muestras de `kilasifen/engine/de/samples/v150` son documentos inventados
(emisor ficticio y firma de relleno). Sirven para probar, no para enviar.

### Validar contra los XSD

```python
errores = rde.validate_xml()    # lista vacía si el documento es válido
```

`validate_xml` necesita `lxml` (incluido en el extra `sign`) y elige el XSD
según el elemento raíz: un `rDE` se valida contra `siRecepDE_v150.xsd`. Para
validar texto XML que no viene de un binding:

```python
from kilasifen.engine.sdk.validation import validate_xml

errores = validate_xml(texto_xml)
```

Ojo: un `RDe` construido con el binding actual siempre reporta al menos la
falta de `dSisFact`. Es una limitación conocida del binding, no de tu
documento.

### Firmar

```python
from pathlib import Path

from kilasifen.engine import sign_xml

pfx = Path("certificado_emisor.p12").read_bytes()
firmado = sign_xml(xml_rde, pfx, "contraseña-del-pfx", cdc)
```

- `xml_rde` puede ser `str`, `bytes` o un elemento `lxml`; `cdc` es el valor
  del atributo `Id` del nodo a firmar (el CDC en un `DE`, el identificador en
  un evento).
- Si después vas a transmitirlo, conviene que el `rDE` use el namespace del
  SIFEN como namespace por defecto, sin prefijos, como el XML que arma la
  plataforma. `enviar_de_xml` inserta el `rDE` sin reescribir sus prefijos,
  así que la firma verifica en los dos casos, pero que el SIFEN acepte un
  `rDE` con prefijos no está verificado.
- La firma es XMLDSig *enveloped*, RSA-SHA256, con canonicalización exclusiva
  y digest SHA-256. La `Signature` queda inmediatamente después del nodo
  firmado y usa el namespace XMLDSig por defecto, sin prefijo `ds:`.
- El PKCS12 se decodifica una sola vez y queda cacheado en el proceso.
- Si el certificado o el documento no permiten firmar, se lanza
  `kilasifen.engine.sdk.errors.SifenSignatureError`.

Desde un binding, `rde.sign_xml(None, pfx, clave, rde.DE.Id)` serializa la
instancia en forma compacta (con el prefijo `ns0:` que asigna xsdata) y la
firma. Para transmitir un binding conviene `TransmisionDE.enviar_de(rde)`, que
lo serializa sin prefijos antes de firmar.

### Hablar con el SIFEN

Requiere el extra `transmision` y el PKCS12 del emisor, que se usa tanto para
firmar como para la autenticación mTLS. Las tres clases reciben `ambiente`
(`TEST` apunta a `sifen-test.set.gov.py`, `PRODUCCION` a `sifen.set.gov.py`),
`pkcs12_data`, `pkcs12_password` y, de forma opcional, `timeout`,
`max_retries` (0 por defecto) y `retry_backoff`. El constructor no abre
conexiones; los recursos (sesión HTTP y PEM temporales) se liberan con
`close()` o al salir del bloque `with`. La clave privada del PEM temporal
queda cifrada con una contraseña aleatoria que nunca se escribe en disco, y la
sesión siempre verifica el certificado del servidor.

**Enviar un DE ya firmado.** Es el camino que usa la plataforma:
`enviar_de_xml` no vuelve a firmar ni pasa el documento por los bindings;
inserta el `rDE` recibido dentro del `rEnviDe` (le agrega `xsi:schemaLocation`
si no lo trae) y lo envía al servicio síncrono de recepción.

```python
from kilasifen.engine import TEST, TransmisionDE

with TransmisionDE(
    ambiente=TEST, pkcs12_data=pfx, pkcs12_password="contraseña-del-pfx"
) as transmision:
    respuesta = transmision.enviar_de_xml(firmado)

protocolo = respuesta.rProtDe
print(protocolo.dEstRes, protocolo.dProtAut)
for resultado in protocolo.gResProc:
    print(resultado.dCodRes, resultado.dMsgRes)
```

`TransmisionDE.enviar_de(rde)` serializa un binding con el namespace del
SIFEN por defecto (sin prefijos), lo firma y lo envía; la firma verifica
dentro del `rEnviDe`. Tené en cuenta que el binding `RDe` tiene el layout
v1.41 (ver la primera limitación del motor).

En los dos caminos, el `rDE` firmado viaja dentro del `rEnviDe` como texto:
conserva sus propias declaraciones de namespace y sus prefijos, de modo que
el `DE` mantiene la forma canónica sobre la que se calculó la firma.

**Errores y reintentos.** Todas las fallas de transporte heredan de
`SifenTransportError`. `SifenRequestNotSentError` indica que la solicitud no
llegó al SIFEN (DNS, conexión rechazada, tiempo agotado al conectar o
handshake TLS fallido) y es seguro volver a enviarla. Cualquier otro error
(`SifenTimeoutError`, conexión cortada, error HTTP) deja el resultado
incierto: consultá por CDC antes de volver a transmitir. Lo mismo vale para
`SifenUnexpectedResponseError`, que se lanza cuando la respuesta es un SOAP
Fault, el sobre de otra operación, HTML de un proxy o un cuerpo que no se
puede leer; su atributo `raw_body` trae el comienzo del cuerpo recibido (no
aparece en el mensaje, porque puede tener datos del contribuyente). Por eso
`TransmisionDE` y `TransmisionEvento` usan `max_retries` solo para
`SifenRequestNotSentError`; las consultas de `ConsultaSIFEN` reintentan
también los timeouts y los cortes.

**Consultar.**

```python
from kilasifen.engine import ConsultaSIFEN

with ConsultaSIFEN(
    ambiente=TEST, pkcs12_data=pfx, pkcs12_password="contraseña-del-pfx"
) as consulta:
    contribuyente = consulta.consultar_ruc("80172649-2")  # acepta RUC-DV
    if contribuyente.xContRUC is not None:
        print(contribuyente.xContRUC.dRazCons)
        print(contribuyente.xContRUC.dRUCFactElec)        # indicador de facturador electrónico

    documento = consulta.consultar_de(cdc)                # 44 dígitos
    print(documento.dCodRes, documento.dMsgRes)
```

`ConsultaSIFEN` también ofrece `consultar_lote(protocolo)`,
`consultar_dte(...)` y `consultar_dte_async(...)`.

**Eventos.** `TransmisionEvento.enviar_evento(grupo)` recibe un
`TgGroupGesEve` (de `kilasifen.engine.de.bindings.v150.evento_v150`), lo
envuelve en `rEnviEventoDe` y lo envía. No firma: el evento tiene que llegar
firmado, y al reserializarse con xsdata una firma calculada sobre otra forma
textual puede dejar de verificar. Para eventos firmados, la plataforma firma el
grupo en `kilasifen/infrastructure/sifen/typed_event_builder.py`, arma el
`rEnviEventoDe` como texto en `kilasifen/infrastructure/sifen/event.py` y lo
envía sin reserializarlo.

**`SifenClient`** agrupa los tres servicios detrás de un solo objeto:

```python
from kilasifen.engine.sdk import SifenClient

with SifenClient(
    ambiente=TEST, pkcs12_data=pfx, pkcs12_password="contraseña-del-pfx"
) as cliente:
    respuesta = cliente.enviar_de_xml(firmado)
    estado = cliente.consultar_de(cdc)
```

Envíos de DE y eventos siempre usan `max_retries=0`; las consultas usan el
`max_retries` del cliente (2 por defecto). Además expone atajos para CDC, QR,
KuDE HTML y espera por polling (`PollingConfig`).

### Utilidades fiscales sin red

```python
from kilasifen.engine.sdk import calculate_mod11_dv, format_cdc_for_kude, generate_cdc

cdc = generate_cdc(
    i_tide=1,
    d_ruc_em="80172649",
    d_dv_emi=2,
    d_est="001",
    d_pun_exp="001",
    d_num_doc="0000148",
    i_tip_cont=2,
    d_fe_emi_de="2026-03-12",
    i_tip_emi=1,
    d_cod_seg="482913076",
)
# "01801726492001001000014822026031214829130767": el CDC de la muestra de factura

calculate_mod11_dv("80172649")  # 2: dígito verificador por módulo 11
format_cdc_for_kude(cdc)        # "0180 1726 4920 ..." en grupos de cuatro
```

- `generate_dcarqr(...)` arma la URL del QR (`dCarQR`) a partir de valores
  sueltos; `generate_dcarqr_from_signed_xml(signed_xml=..., id_csc=..., csc=...,
  environment="test")` los toma del propio XML firmado. Con
  `xml_escaped=True` devuelven la URL lista para insertar en el XML.
- `render_kude_html(rde)` y `save_kude_html(rde, ruta)` generan una
  representación imprimible en HTML. El KuDE en PDF lo produce la plataforma.

### Regenerar los bindings

El código de `kilasifen/engine/de/bindings/v150` salió de xsdata 26.2. La
configuración del generador está en el propio script, sin archivo aparte.

```bash
pip install "xsdata[cli]==26.2"
python scripts/generate_bindings.py           # reescribe kilasifen/engine/de/bindings/v150
python scripts/generate_bindings.py --check   # falla si lo versionado no coincide con los XSD
```

El script procesa los XSD en orden alfabético y, cuando dos esquemas definen
el mismo nombre, xsdata conserva la última definición. Por eso el orden es
fijo, y por eso `RDe` termina saliendo de `FE_v141.xsd`. Nunca edites a mano
los archivos generados: cambiá el XSD o el script y volvé a generar.

Para saber si la SET publicó esquemas nuevos (consulta su sitio y no envía
ningún documento):

```bash
CHECK_SCHEMA_UPDATES=1 python -m pytest tests/test_schema_versions.py::TestSchemaUpdates
```

## Tipos de documento electrónico (v150)

`DE_Types_v150.xsd` admite `iTiDE` con el patrón `1|[4-7]|9|10`.

| `iTiDE` | Documento | API tipada | Muestra en el repo |
| --- | --- | --- | --- |
| 1 | Factura electrónica | Sí | `factura_electronica.xml` |
| 4 | Autofactura electrónica | No | `autofactura.xml` |
| 5 | Nota de crédito electrónica | Sí | `nota_credito.xml` |
| 6 | Nota de débito electrónica | Sí | `nota_debito.xml` |
| 7 | Nota de remisión electrónica | No | `nota_remision.xml` |
| 9 | Boleta de venta electrónica | No | No |
| 10 | Boleta resimple electrónica | No | No |

Los códigos 2 (exportación), 3 (importación) y 8 (comprobante de retención)
aparecen comentados en el XSD oficial y el patrón de `iTiDE` no los admite. El
binding del `rDE` no cubre por igual todos los tipos de la tabla (ver
[Limitaciones conocidas](#limitaciones-conocidas)). El recibo
electrónico de dinero no tiene endpoint: la razón está en
[`docs/architecture/adr-0002-recibo-electronico.md`](docs/architecture/adr-0002-recibo-electronico.md).

## Desarrollo y pruebas

Para correr todo, incluida la plataforma, usá Python 3.11 o superior:

```bash
pip install -e ".[sign,transmision,test]"
python -m pytest -q
python -m ruff check kilasifen tests --select F
```

El workflow de CI corre ruff solo con las reglas `F`. Con el conjunto completo
de `pyproject.toml` (`E`, `F`, `I`, `W`), hoy quedan avisos `E501` (líneas
largas) en módulos de la plataforma y en algunas pruebas.

Con [uv](https://docs.astral.sh/uv/),
`uv sync --frozen --extra sign --extra transmision --extra test` instala el
entorno fijado en `uv.lock`, igual que el workflow de CI.

- Las pruebas no contactan al SIFEN: la transmisión se prueba con dobles. La
  verificación de esquemas nuevos, que consulta el sitio de la SET, solo corre
  si activás `CHECK_SCHEMA_UPDATES=1`.
- `tests/conftest.py` genera en cada sesión un PKCS12 descartable en
  `tests/test_cert.pfx` (contraseña `test1234`) y lo borra al terminar. No
  ejecutes dos sesiones de pytest en paralelo sobre la misma copia del
  repositorio.
- Las pruebas de concurrencia contra PostgreSQL se saltean salvo que definas
  `KILA_SIFEN_TEST_DATABASE_URL`.
- Las pruebas de transmisión que verifican el handshake TLS abren un socket en
  `127.0.0.1` (loopback); ningún paquete sale de la máquina.
- Si cambiás rutas o schemas de la API, regenerá el contrato con
  `python scripts/export_openapi.py` (con `--check` solo verifica).

Las reglas para contribuir están en [CONTRIBUTING.md](CONTRIBUTING.md).

## Limitaciones conocidas

### Motor

1. **El binding del `rDE` tiene el layout de la versión 1.41.** El único `RDe`
   generado sale de `FE_v141.xsd`, porque xsdata conserva la última definición
   en orden alfabético. No conoce elementos exclusivos de v150 como
   `dSisFact` (el parser los rechaza) y `validate_xml()` siempre informa su
   ausencia. Su restricción de `iTiDE` es `1|[5-6]` y su enumeración de
   `dDesTiDE` solo incluye factura, nota de crédito y nota de débito: las
   muestras de autofactura (4) y remisión (7) se leen y se vuelven a escribir,
   pero xsdata emite un `ConverterWarning` y deja la descripción como texto.
   Las boletas (9 y 10) no tienen muestras ni pruebas. En producción, la
   plataforma no usa este binding: arma el XML con su propio constructor
   ElementTree (`kilasifen/infrastructure/sifen/typed_xml_builder.py`) y lo
   valida contra `siRecepDE_v150.xsd` antes de firmar.
2. **`enviar_lote` no respeta el formato del SIFEN.** Codifica el contenido
   dos veces en base64 y no lo comprime en ZIP. La plataforma no lo usa.
3. **`consultar_dte_async` se reintenta como si fuera una consulta de solo
   lectura** (por ejemplo, con el `max_retries` de `SifenClient`), aunque
   registra una solicitud en el SIFEN.

### Plataforma

Hallazgos de una auditoría reciente, que se corregirán a continuación:

- Si el payload no trae `codigo_seguridad`, se usa la constante `123456789`.
- La dirección, el teléfono, el correo y la actividad económica del emisor
  reciben valores ficticios por defecto cuando faltan.
- El QR de producción siempre usa el parámetro `dRucRec`, incluso cuando el
  receptor se identifica con `dNumIDRec`.
- Solo el código `0260` (o el estado "Aprobado") cuenta como aprobación;
  cualquier otro código se clasifica como rechazo, así que nunca se produce
  `approved_with_observation` a partir de una respuesta real.
- Un evento (cancelación o inutilización) con resultado incierto se vuelve a
  enviar en el intento siguiente, sin consultar antes; la regla definitiva
  depende de cómo trata el SIFEN un evento duplicado.
- Si el worker muere mientras espera al SIFEN, el job queda `processing` (el
  documento, `submitting`) hasta que un operador lo reencola desde la consola;
  ese reintento consulta el CDC antes de decidir. No hay un proceso que
  detecte esos jobs solo.

KilaSifen no certifica conformidad fiscal. Probá cada flujo en el ambiente
de pruebas de la SET antes de habilitar producción.

## Seguridad

No abras issues públicos por vulnerabilidades. Reportalas en privado mediante
el [reporte privado de GitHub](https://github.com/ras272/kilasifen/security/advisories/new);
el procedimiento completo está en [SECURITY.md](SECURITY.md).

No subas al repositorio certificados, contraseñas, CSC, API keys ni archivos
`.env`. Las muestras y los certificados de las pruebas son ficticios o se
generan en el momento.

## Licencia

MIT. Copyright (c) The KilaSifen Authors. El texto completo está en
[MIT-LICENSE](MIT-LICENSE).
