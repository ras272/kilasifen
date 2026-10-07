# CLAUDE.md — guía para agentes en KilaSifen

Este archivo orienta a los agentes de código que trabajan en el repositorio.
Se lee junto con `AGENTS.md`, que fija las reglas generales de ejecución
(calidad, validación, commits, capas, secretos, compatibilidad). Si algo de
esta guía parece contradecir `AGENTS.md`, prevalece `AGENTS.md` y conviene
señalar la contradicción en el commit o PR.

## Reglas duras

1. Nada bajo `kilasifen/engine/de/bindings/` se edita a mano. Se regenera con
   `scripts/generate_bindings.py`.
2. `kilasifen/engine` no importa código de la plataforma (`kilasifen.api`,
   `application`, `domain`, `infrastructure`, `repositories`, `admin`,
   `config`, `testing`, ...). Lo único que toma de `kilasifen` es
   `__version__`.
3. Toda firma XMLDSig sale de `kilasifen/engine/sdk/signer.py`, directamente
   o a través de `kilasifen.engine.firma.sign_xml`. No se escribe una segunda
   implementación de firma.
4. Los tests no hacen llamadas de red ni usan datos, RUC, CSC o certificados
   reales. Quedan excepciones heredadas que hay que limpiar (ver «Deuda
   conocida»); no se suman nuevas.
5. Clean-room: no vuelve al repositorio nada del import original de terceros
   (ver la sección «Regla clean-room»).
6. Los envíos de DE y de eventos no se reintentan a ciegas ante un resultado
   incierto: reenviar un documento cuyo resultado se desconoce puede
   duplicarlo ante la SET. `TransmisionDE` y `TransmisionEvento` solo repiten
   una solicitud que no llegó al SIFEN (`SifenRequestNotSentError`), aun con
   `max_retries > 0`; la plataforma y `SifenClient` igual los usan con
   `max_retries=0`. La plataforma consulta el CDC (siConsDE) antes de
   reenviar: un DE solo vuelve a viajar cuando la consulta responde `0420`, el
   request no salió o el rechazo fue `0161`/`0162` o un `0160` solo y sin
   detalle de validación, y siempre es el mismo `rDE` firmado en un `rEnviDe`
   nuevo; una cancelación incierta se verifica en `xContEv` antes de
   reenviarse (`docs/normativa/matriz.md`, decisiones F60-F64, F67 y F70).

## Qué es KilaSifen

KilaSifen es una API fiscal *headless* para emitir, firmar, transmitir y
consultar documentos electrónicos ante el SIFEN de Paraguay. La plataforma
corre sobre FastAPI, PostgreSQL y Redis/RQ, con un outbox transaccional para
despachar jobs de forma durable. Debajo hay un motor Python propio,
`kilasifen.engine`, que aporta los bindings de los XSD oficiales, la firma
XMLDSig, el transporte SOAP con mTLS y utilidades fiscales (CDC, DV, QR,
KuDE).

En el mismo repositorio viven el portal de documentación (`apps/docs`) y el
SDK oficial en TypeScript (`sdks/typescript`). La versión actual es `0.2.0`
(`kilasifen.__version__`) y todavía no se publicó ni en PyPI ni en npm.

Licencia MIT. La autoría figura como «The KilaSifen Authors» en
`pyproject.toml`, y el aviso de copyright de `MIT-LICENSE` tiene que decir lo
mismo. Las vulnerabilidades se reportan por el canal privado de GitHub que
describe `SECURITY.md`, nunca en un issue público.

## Mapa del repositorio

```
kilasifen/
  __init__.py          __version__
  config.py            Settings (pydantic-settings, prefijo KILA_SIFEN_)
  logging.py  observability.py  security.py
  api/                 FastAPI: app.py (create_app), routers/, schemas/,
                       deps.py (cableado de dependencias), errors.py, middleware.py
  application/         servicios de caso de uso por área (documents, events,
                       emitters, certificates, stampings, queries, jobs,
                       webhooks, access, admin, health, sandbox)
  domain/              modelos y estados fiscales; sin FastAPI ni SQLAlchemy
  repositories/        interfaces abstractas de persistencia
  infrastructure/
    db/                SQLAlchemy: modelos, sesión y repositorios concretos
    sifen/             typed_xml_builder, typed_event_builder, gateway al engine
    jobs/              cola RQ, workers y outbox_worker
    kude/  crypto/  webhooks/  limits/  sandbox/
  admin/               consola administrativa (router + plantillas Jinja)
  testing/             helpers de test (base aislada, escenarios tipados)
  engine/
    __init__.py        fachada pública estable
    binding.py         BindingMixin (base de todas las clases generadas)
    firma.py           sign_xml
    transmision/       base, conexion, config, de, consulta, evento
    sdk/               client, fiscal, kude, polling, validation, signer, errors
    de/schemas/v150/   XSD oficiales de la SET
    de/bindings/v150/  bindings generados por xsdata
    de/samples/v150/   muestras XML ficticias (tipos 1, 4, 5, 6 y 7)
alembic/               migraciones (versions/AAAAMMDD_NN_descripcion.py)
apps/docs/             portal Fumadocs (Next.js), con su propio AGENTS.md/CLAUDE.md
sdks/typescript/       SDK @kilasifen/sdk
scripts/               generate_bindings.py, export_openapi.py, preview_kude.py
docs/                  arquitectura y ADR, operaciones, normativa, integración,
                       ejemplos ejecutables; superpowers/ y progress/ son
                       registros históricos de planificación, no fuente de verdad
tests/                 en la raíz (test_*.py) el engine más config, logging,
                       observability y los scripts de docs/examples;
                       plataforma en api/, application/,
                       domain/, infrastructure/; golden/ con XML de
                       referencia; _muestras.py; conftest.py
Dockerfile  docker-compose.yml (api, worker, outbox, migrate, postgres, redis)
```

## Comandos

### Entorno

```bash
# Desarrollo completo: engine + plataforma + herramientas de test (ruff, mypy)
pip install -e ".[sign,transmision,test]"
# o, respetando uv.lock:
uv sync --frozen --extra sign --extra transmision --extra test
```

Extras disponibles: `sign` (firma), `soap` (cliente SOAP de xsdata),
`transmision` (firma + transporte), `platform` (dependencias de la API y los
workers) y `test`. Sin extras, `import kilasifen.engine` funciona igual: las
dependencias pesadas se importan recién al usarlas.

### Tests

```bash
python -m pytest -q                       # suite completa
python -m pytest tests/test_*.py -q       # engine + config/logging/observability
python -m pytest tests/api tests/application tests/domain tests/infrastructure -q
```

- `tests/conftest.py` genera en cada sesión un PKCS#12 efímero en
  `tests/test_cert.pfx` (contraseña `test1234`) y lo borra al terminar. No
  correr dos sesiones de pytest en paralelo sobre el mismo árbol: una pisa o
  elimina el certificado de la otra.
- Sin `KILA_SIFEN_TEST_DATABASE_URL` los tests de plataforma usan SQLite.
  Apuntándola a PostgreSQL, cada test trabaja en un schema propio; el marcador
  `requires_postgres` identifica los que necesitan ese backend.
- Referencia medida el 2026-10-07 (Python 3.14, sin
  `KILA_SIFEN_TEST_DATABASE_URL`, `python -m pytest tests/ -q`): 2119 passed,
  10 skipped (ocho de ellos solo corren contra PostgreSQL). Ya no queda ningún
  xfail. Si el número cambia, que sea por tests agregados o quitados a
  propósito.
- Chequeo de versiones nuevas de los XSD en la SET (hace red; se corre a mano
  o desde el job semanal del workflow):
  `CHECK_SCHEMA_UPDATES=1 python -m pytest tests/test_schema_versions.py::TestSchemaUpdates`.
- Prueba real contra el SIFEN de test (hace red; sólo `sifen-test.set.gov.py`,
  con producción bloqueada en el proceso): `scripts/sifen_test_smoke.py`. Los
  datos del emisor van en `.sifen-test/config.json` (fuera de git) y la
  contraseña del certificado en el Administrador de credenciales de Windows
  (`cmdkey /generic:kilasifen-sifen-test /user:sifen-test /pass`), nunca en
  argumentos, variables ni archivos. `--dry-run` arma y valida sin red.

### Lint

```bash
python -m ruff check kilasifen tests scripts
```

La configuración vive en `pyproject.toml` (`[tool.ruff]`); E501 solo se
ignora dentro de los bindings generados. `kilasifen/engine` pasa sin
hallazgos. En la plataforma, en tests y en `scripts/preview_kude.py` quedan
líneas largas (E501) anteriores a esta guía: no sumar nuevas.

### Bindings

```bash
pip install "xsdata[cli]==26.2"
python scripts/generate_bindings.py          # regenera de/bindings/v150
python scripts/generate_bindings.py --check  # falla si lo versionado difiere
```

La configuración de xsdata vive en el propio script (no hay `.xsdata.xml`).
Hoy la generación imprime avisos esperables: «Duplicate type ... will keep
the last defined», «Resource not found ... RDE_Group.xsd» (y su variante
Ekuatiai) y «Module not found on imports validation». Lo que importa es que
`--check` termine con «Bindings al dia.».

### Contrato OpenAPI

```bash
python scripts/export_openapi.py            # reescribe apps/docs/public/openapi.json
python scripts/export_openapi.py --check    # falla si el contrato quedó desactualizado
```

Cualquier cambio en routers o schemas de la API exige regenerar el contrato y
revisar el portal y el SDK TypeScript.

### Migraciones

```bash
alembic upgrade head             # usa KILA_SIFEN_DATABASE_URL o la URL de alembic.ini
alembic current --check-heads
```

Cada cambio de modelo lleva una migración nueva con revisión `AAAAMMDD_NN`
encadenada a la anterior. Las migraciones ya aplicadas no se modifican.

### Levantar la plataforma

```bash
cp .env.example .env    # completar secretos y URLs
docker compose up --build
```

Procesos por separado: `uvicorn kilasifen.api.app:create_app --factory`,
`rq worker documents events webhooks -u $KILA_SIFEN_REDIS_URL` y
`python -m kilasifen.infrastructure.jobs.outbox_worker`. Los tres son
obligatorios: sin el outbox ningún job llega al worker. `.env.example` deja en
`true` `KILA_SIFEN_DOCUMENT_AUTO_ENQUEUE` (lo lee la API) y
`KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS` (lo lee el worker); en el código valen
`false`.

Staging en Railway: `docs/DEPLOYMENT.md`. La migración corre como pre-deploy
de la API, el healthcheck de Railway es `/v1/health` (no `/v1/ready`, que
exige worker y outbox) y un start command con variables va envuelto en
`/bin/sh -c "exec ..."`. `tests/test_deployment_artifacts.py` vigila Compose,
el workflow de CI y ese runbook.

### Portal y SDK TypeScript

Con pnpm, dentro de cada carpeta: `apps/docs` → `pnpm lint`, `pnpm typecheck`,
`pnpm build`; `sdks/typescript` → `pnpm lint`, `pnpm test`, `pnpm build`.
Antes de tocar `apps/docs`, leer su `AGENTS.md`.

## Engine (`kilasifen.engine`)

- **Fachada pública.** `kilasifen.engine` exporta `__version__`, `sign_xml`,
  `PRODUCCION`, `TEST`, `ENDPOINTS`, `get_endpoint`, `TransmisionDE`,
  `ConsultaSIFEN` y `TransmisionEvento`. Cambiar ese conjunto rompe
  `tests/test_public_api.py` y el smoke test del CI; si es inevitable, se
  documenta la migración (regla 8 de `AGENTS.md`).
- **Bindings.** Cada clase generada hereda de `BindingMixin` (`from_xml`,
  `from_path`, `to_xml`, `validate_xml`, `sign_xml`); la herencia la inyecta el
  generador, no se agrega a mano. Los atributos llevan la etiqueta tal cual
  figura en el XSD (por ejemplo `iTiDE`, `dNumTim`, `gCamItem`); las clases
  quedan en PascalCase y los módulos en snake_case, con el nombre del XSD de
  origen. Hay menos módulos que XSD (26 para 47 archivos): un XSD cuyos tipos
  ya estaban definidos en otro, o que solo declara tipos simples, no deja
  módulo propio (ver «Esquemas XSD»).
- **Estilo.** Docstrings y comentarios en español sin tildes (ASCII), type hints
  en todo lo público y `from __future__ import annotations` en los módulos
  nuevos. Varios módulos de `sdk/` (`client.py`, `fiscal.py`, `kude.py`,
  `polling.py`, `validation.py`) todavía tienen docstrings en inglés o
  portugués: al tocarlos, se pasan a español.
- **Compatibilidad.** Todo el proyecto declara Python 3.10 como mínimo: no usar
  `datetime.UTC` (usar `timezone.utc`), `typing.Self`, `tomllib`, `StrEnum` ni
  otras APIs 3.11+, y no pasar a `datetime.fromisoformat` textos con sufijo `Z`
  sin normalizarlos. Para verificarlo sin un intérprete 3.10, correr la suite
  con `datetime.UTC` borrado (ver el commit `f4d8315`).
- **Firma.** `sdk/signer.py` implementa la firma *enveloped* RSA-SHA256 (C14N
  exclusiva, digest SHA-256, sin prefijo `ds:`) y guarda en una caché LRU los
  firmadores PKCS#12 ya decodificados. `firma.sign_xml` es la entrada pública:
  la usan `BindingMixin.sign_xml` y `infrastructure/sifen/engine.py`.
  `TransmisionBase` y `infrastructure/sifen/typed_event_builder.py` piden el
  firmador directamente con `sdk.signer.get_pkcs12_signer`. La caché es por
  proceso. Los jobs de documentos y eventos la vacían al terminar
  (`clear_pkcs12_signer_cache` en `infrastructure/jobs/workers.py`), así que
  ningún worker conserva claves descifradas entre jobs;
  `CertificateService.activate_certificate` además la vacía en el proceso que
  activa, como defensa en profundidad.
- **Transporte.** `TransmisionBase` arma el cliente SOAP con mTLS; endpoints y
  ambientes salen de `transmision/config.py`. La sesión HTTPS sale de
  `transmision/conexion.py`: un `HTTPAdapter` con `ssl.SSLContext` propio
  carga el certificado del emisor y su clave privada, que se escribe en disco
  como PKCS#8 cifrado con una contraseña aleatoria que solo vive en memoria.
  La verificación del certificado del servidor queda siempre activada. La
  plataforma arma el `rEnviDe` con `_build_enviar_de_request_xml` y el `dId`
  real, lo guarda con el documento y lo envía tal cual con
  `TransmisionDE._send_raw_xml`, no con `enviar_de(rde)`. Los mensajes salen
  sin prefijos de namespace (MT v150 §7.2): el serializador compartido de
  `base.py` deja el namespace del SIFEN por defecto, también en los clientes
  xsdata.
- **Lote.** `transmision/de.py` arma el ZIP del lote (`_build_lote_zip`):
  una entrada `.xml` con `<rLoteDE>` sin namespace, una sola declaración y
  los `rDE` sin blancos; al binding `REnvioLote.xDE` se le pasan los bytes
  del ZIP, porque él ya codifica en base64. `sdk/polling.py` aplica los
  códigos de la consulta de lote (solo `0361` es pendiente) con intervalos de
  600 s por defecto. Las reglas y sus fuentes están en
  `docs/normativa/matriz.md`.

## Plataforma

- **Capas.** `api/routers` → `application/*/service.py` → interfaces de
  `repositories/`, implementadas en `infrastructure/db/repositories/`. El
  cableado está en `api/deps.py`. Un router no habla con la base ni con
  SQLAlchemy. `domain/` no depende de frameworks. Algunos servicios de
  `application/` todavía importan piezas concretas de `infrastructure/`
  (cifrado, gateways del SIFEN, webhooks); no sumar acoplamientos de ese tipo.
- **Contratos.** Requests y responses tipados con Pydantic en `api/schemas/`;
  errores con el formato común de `api/errors.py`.
- **XML de producción.** Lo arma `infrastructure/sifen/typed_xml_builder.py`
  con ElementTree y se valida contra `siRecepDE_v150.xsd`
  (`engine.sdk.validation`) antes de firmar; la validación descarta dos
  errores esperables (la `Signature` todavía ausente y un defecto conocido del
  XSD en `dEntCont`). No se emite a través del binding `RDe`, que tiene el
  layout v141 (ver «Esquemas XSD»). `gEmis` sale sólo del emisor y de su
  perfil fiscal persistido (`domain/emitters/fiscal_profile.py`); `gDatRec`,
  de `domain/documents/receiver.py`, que también usa la API; los montos de
  `gCamItem`, `gTotSub` y `gCamCond` (IVA por ítem con las fórmulas de la
  NT 13, 2 decimales en PYG y 8 en otras monedas, subtotales, descuento
  global, redondeo opcional y pagos), de `domain/documents/totals.py`, el
  mismo calculador que valida la API; `dCodSeg` se
  elige al crear el documento (`documents.security_code`) y `dFecFirma` es
  la hora de la firma. Antes de firmar `dCarQR` lleva un marcador sin datos
  fiscales (`DCARQR_PENDING_SIGNATURE`); después de firmar
  `infrastructure/kude/xml_qr_injector.py` lo reemplaza con
  `engine.sdk.fiscal.build_qr_payload_from_signed_xml`, la única
  implementación del QR (literales del XML firmado). Las reglas y sus
  fuentes están en `docs/normativa/matriz.md`. El `generated_xml` del endpoint raw
  deprecado pasa por `infrastructure/sifen/raw_xml_policy.py` al crearse
  (`DocumentService.create_raw_document`, con la política inyectada desde
  `api/deps.py` y aplicada después de la búsqueda idempotente)
  y otra vez en el mapper antes de firmar: el `rDE` sólo puede tener
  `dVerFor`, un `DE`, una `Signature` opcional y `gCamFuFD`; se valida una
  copia con una `Signature` de relleno, sin tolerar su ausencia, y la firma
  referencia siempre el `Id` de ese `DE`. Un `signed_xml` enviado por el
  caller se rechaza y nunca se transmite.
- **Configuración y secretos.** Todo sale de variables `KILA_SIFEN_*`
  (`kilasifen/config.py`, `.env.example`). CSC, PFX y contraseñas se guardan
  cifrados y las respuestas de la API no los devuelven (el emisor expone
  `csc_configured`, no el CSC). Los logs no deben exponer datos sensibles
  (regla 9 de `AGENTS.md`).

## Esquemas XSD

- Los XSD de `kilasifen/engine/de/schemas/v150/` son los oficiales de la SET
  (<https://ekuatia.set.gov.py/sifen/xsd/>, namespace
  `http://ekuatia.set.gov.py/sifen/xsd`). La carpeta toma el nombre del Manual
  Técnico 150, pero adentro conviven archivos con sufijo `_v150`, `_v141` y
  `_v100`, y algunos sin sufijo, porque así los distribuye la SET.
- Los `xs:import`/`xs:include` resuelven siempre contra archivos de esta misma
  carpeta, nunca contra una URL. Si se suma un XSD bajado de la SET, sus
  referencias se reescriben a nombres de archivo locales antes de generar.
- El generador recorre los XSD ordenados por nombre y, cuando un tipo aparece
  repetido, xsdata conserva una sola definición. En la práctica el único `RDe`
  generado está en `fe_v141.py` (layout de `FE_v141.xsd`) y no tiene campos
  propios de v150 como `dSisFact`.
- Una versión nueva del Manual se agrega como carpeta hermana y se genera con
  `python scripts/generate_bindings.py --version <carpeta>`.

## Tipos de documento electrónico en v150

`DE_Types_v150.xsd` acepta `iTiDE` con el patrón `1|[4-7]|9|10`:

| iTiDE | Documento | Muestra en `samples/v150` | API tipada |
|------:|-----------|:-------------------------:|:----------:|
| 1  | Factura electrónica          | sí | sí |
| 4  | Autofactura electrónica      | sí | no |
| 5  | Nota de crédito electrónica  | sí | sí |
| 6  | Nota de débito electrónica   | sí | sí |
| 7  | Nota de remisión electrónica | sí | no |
| 9  | Boleta de venta electrónica  | no | no |
| 10 | Boleta resimple electrónica  | no | no |

Los códigos 2 (exportación), 3 (importación) y 8 (comprobante de retención)
quedan fuera de ese patrón y sus descripciones aparecen comentadas en el XSD
oficial: no son válidos en v150. Los tipos 9 y 10 no tienen muestra porque el
binding `fe_v141` no los representa (`tests/_muestras.py` registra el motivo
de cada ausencia). La API tipada
expone facturas, notas de crédito y notas de débito, más los eventos de
cancelación e inutilización; el endpoint raw queda reservado a administradores
de la plataforma.

## Tests: convenciones

- Cada cambio de comportamiento trae su test nuevo o ajustado (regla 3 de
  `AGENTS.md`).
- `tests/_muestras.py` es la única fuente de los valores de las muestras. Los
  tests no repiten literales sacados de los XML: los toman de `MUESTRAS` o de
  las constantes del registro. Una muestra nueva se registra ahí con datos
  ficticios coherentes (RUC con DV válido, CDC calculado con
  `sdk.fiscal.generate_cdc`).
- Los tests de transporte usan dobles (sesiones y transportes falsos); nunca
  llegan al SIFEN, ni siquiera al ambiente de pruebas. La única excepción es el
  chequeo de XSD activado con `CHECK_SCHEMA_UPDATES=1`.
- El certificado de test es efímero y lo crea `conftest.py`; `*.pfx` está en
  `.gitignore` y ningún certificado se commitea.
- Los XML de `tests/golden/` se comparan con lo que genera la plataforma
  después de quitar la `Signature` (la clave de test cambia en cada sesión) y
  volver a serializar con ElementTree. Se regeneran solo a propósito, con
  `KILA_SIFEN_UPDATE_GOLDENS=1`, y revisando el diff. `.gitattributes` fija LF
  para todo el repositorio.
- Un `xfail(strict=True)` marca un defecto conocido. Quien lo corrija quita el
  marcador en el mismo cambio.

## Regla clean-room

El repositorio arrancó con un import de un motor de terceros (commit
`e82dc01`, con rutas `pysifen/`). El código del engine, sus tests y sus
muestras se reescribieron desde cero. De aquel commit todavía quedan los XSD
oficiales de la SET (con las referencias ajustadas a archivos locales) y los
dos documentos de `docs/superpowers/` fechados 2026-04-22, que son el diseño y
el plan del fork escritos por este proyecto. Para no volver atrás:

- No copiar, adaptar ni parafrasear código, comentarios, docstrings, tests o
  documentación de `e82dc01` ni de ninguna ruta `pysifen/` del historial, y no
  usarlos como referencia para escribir código nuevo.
- No reintroducir los nombres ni la estructura de aquel import (`CommonMixin`,
  `assinatura`, `transmissao`, `.xsdata.xml`, `script.sh`, clases `Pysifen*`).
- Las fuentes válidas son la documentación oficial de la SET (Manual Técnico,
  XSD, notas técnicas), el código y los tests actuales y las decisiones
  registradas en `docs/`, salvo los documentos heredados de `e82dc01`.
- Ante la duda sobre el origen de un fragmento, preguntar antes de usarlo.

## Idioma y commits

- Documentación, portal y engine: español. Los nombres nuevos del engine siguen
  el idioma del módulo donde se agregan; las etiquetas del SIFEN se usan tal
  cual.
- Plataforma: docstrings y mensajes internos en el idioma que ya usa cada
  módulo (hoy mayormente inglés); los textos dirigidos a integradores (portal,
  resúmenes del OpenAPI) van en español.
- Commits en inglés con Conventional Commits: `feat:`, `fix:`, `refactor:`,
  `docs:`, `test:`, `chore:`, `style:`, con `!` cuando rompen compatibilidad.
  Por ejemplo, `fix: classify approved-with-observation responses`.
  `AGENTS.md` pide commitear cada cambio terminado.

## Deuda conocida

Engine (defectos que la reescritura clean-room conservó a propósito para
mantener el mismo comportamiento; se corrigen en commits posteriores):

- La consulta DTE (`cons_dte`, `cons_dte_async`) es experimental: solo hay
  XSD, sin dirección, códigos ni plazos oficiales. Emite
  `SifenExperimentalWarning`; no inventar tokens de "pendiente" ni rutas
  nuevas sin una fuente oficial.
- `consultar_dte_async` se reintenta como si fuera una consulta de solo
  lectura.
- El lote (`enviar_lote`, `enviar_lote_xml`) ya sigue el formato oficial,
  pero la plataforma todavía no envía por lote ni usa
  `kilasifen.engine.sdk.polling`; el nombre del archivo del ZIP y la medida
  de 1000 KB son decisiones NO DETERMINADO registradas en
  `docs/normativa/matriz.md`.
- El único binding `RDe` tiene el layout v141 (sin `dSisFact`).
- `TransmisionDE.enviar_de(rde, sign=True)` firma sin recalcular `dCarQR`,
  que depende del `DigestValue` de la firma; la plataforma no lo usa.

Plataforma (hallazgos de auditoría pendientes):

- Una inutilización con resultado incierto se reenvía sin verificación
  previa, porque ningún servicio oficial permite consultarla; un `4066`
  posterior queda `reconciliation_required` para un operador. Lo mismo
  una cancelación con `4003` cuya cancelación no aparece en `xContEv` (o
  con un `xContenDE` ilegible) y una cuyo CDC responde `0420`. No existe un
  endpoint para resolver a mano esos eventos: reintentar el job (consola o
  `POST .../jobs/{job_id}/retry`) repite la consulta o el envío.
- Un reenvío del mismo DE (tras `0420`, `0161`/`0162` o `0160` sin detalle)
  no vuelve a controlar la ventana de `dFeEmiDE` (1150/1151, MT v150 §12.4
  val. 19-20): solo deja el aviso en `deadline_alerts`.
- `KilaSifenQueryGateway.query_ruc` guarda para auditoría un request con un
  `dId` distinto del que viajó (`query_document` ya guarda el real).
- La respuesta de `GET /documents/{id}` (`api/schemas/documents.py`) todavía
  no expone `sifen_approved_at`, `sifen_protocol`, `sifen_messages` ni
  `retryable_server_error`: quedan en la base (el protocolo también sale en la
  consulta por CDC y el reenvío por `0161`/`0162` en el `error_snapshot` del
  job).
- Los puntos que la normativa deja abiertos en respuestas, reenvíos, eventos e
  inutilización (`0161`/`0162`, reglas del `dId`, `0420` de un DTE cancelado,
  hora de aprobación por consulta, entre otros) siguen la opción documentada
  en `docs/normativa/matriz.md`; conviene confirmarlos en el ambiente de test
  de la SET. El 2026-10-06 ese ambiente aprobó facturas, NC y ND con IVA de 2
  decimales, una cancelación y una inutilización, y mostró la forma real de
  `xContenDE`. También respondió a veces `0160` «XML Mal Formado» (HTTP 400)
  a pedidos válidos que pasaron segundos después. Un DE rechazado sólo con
  ese `0160` sin detalle se reenvía como un `0161`/`0162` (decisión F67); un
  evento rechazado así no: los eventos no tienen esa regla ni la de F64.
- `KilaSifenEmissionEngine` sin `mapper` lee
  `KILA_SIFEN_TEST_EMITTER_NAME_LITERAL` con `get_settings()`; los workers
  deberían pasar el literal explícito. El literal correcto del ambiente de
  pruebas (MT 1263 frente a la Guía de Pruebas 2026) sigue NO DETERMINADO.
- `infrastructure/sifen/typed_event_builder.py` todavía rechaza cualquier
  texto que contenga «ds:» (el builder de documentos ya sólo rechaza markup
  `ds:` real).
- `establecimiento`/`punto` siguen con default `001` cuando el payload no los
  trae.
- Quedan defaults fiscales anteriores a la regla «ningún dato se inventa»:
  contado con un pago en efectivo si no viene `condicion_operacion`
  (`domain/documents/totals.py`), D011/D013/E011 e `iMotEmi` en 1, `dCodInt`
  `ITEMnnn`, tasa 10 en `api/schemas/documents.py` y `dDesUniMed` `UNI` para
  cualquier `cUniMed` (`typed_xml_builder.py`); con una unidad distinta de
  77 sin `descripcion_unidad` el SIFEN rechaza con 1802 (MT v150 §12.4,
  p. 174).
- El emisor guarda un solo CSC sin historial. El QR se calcula al firmar y
  un reenvío conserva el XML firmado, pero no hay forma de regenerar el QR
  de un DE ya emitido con el CSC vigente en su `dFeEmiDE` (2501, NT 10 §4).
- Las opciones de QR y KuDE que la SET no determina (forma de los montos
  en el QR, receptor B2F sin documento, *quiet zone*, separadores de los
  montos impresos, ítem gravado parcial en las columnas del KuDE, KuDE de un
  DTE cancelado) están en las notas 12-14 de `docs/normativa/matriz.md`. El
  KuDE imprime cada número con todos los dígitos del XML (MT v150 §13.2):
  nunca redondearlo.
- Qué deben sumar los pagos y el alcance del redondeo a 50 Gs siguen NO
  DETERMINADOS por la SET (notas 9 y 10 de `docs/normativa/matriz.md`); la
  plataforma aplica la opción documentada allí.
- Un job cuyo worker muere durante la llamada al SIFEN queda `processing`
  (documento `submitting`) hasta que alguien lo reencola (la consola o
  `POST /v1/emitters/{emitter_id}/jobs/{job_id}/retry`, que también usa el
  ERP); no hay reaper que lo detecte solo. El reintento consulta el CDC antes
  de decidir.

Proyecto:

- `tests/test_ares_de_test_xml.py` ejercita
  `docs/examples/send_ares_factura_test.py`, que trae RUC, razón social y
  timbrado con aspecto de datos reales de un contribuyente; el certificado
  efímero de `conftest.py` usa ese mismo RUC. Hay que pasarlos a datos
  ficticios. El mismo emisor (80024135) y el receptor 80069563 siguen en
  fixtures anteriores (escenarios de `kilasifen/testing/typed_contract_scenarios.py`,
  goldens y emisores de prueba de `tests/api`); los tests nuevos usan los
  ficticios de `kilasifen/testing/typed_documents.py`.
- El workflow `.github/workflows/tests.yml` (push a `main`, PR contra
  cualquier rama y semanal) nunca completó una corrida por fallas de arranque
  a nivel de cuenta. No afirmar que el CI está en verde: validar localmente.
  El job `platform-tests` corre cada carpeta de `tests/` con pruebas;
  `tests/test_deployment_artifacts.py` falla si se agrega una carpeta nueva
  sin sumarla a ese job.
