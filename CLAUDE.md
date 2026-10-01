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
6. Los envíos de DE y de eventos no se reintentan: `max_retries` queda en `0`.
   Reenviar un documento cuyo resultado se desconoce puede duplicarlo ante la
   SET.

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
    transmision/       base, config, de, consulta, evento
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
- Referencia medida al escribir esta guía (commit `9c714f3`, Python 3.14, sin
  `KILA_SIFEN_TEST_DATABASE_URL`): 1092 passed, 6 skipped, 1 xfailed. El
  xfail es estricto y documenta un defecto conocido (ver «Deuda conocida»).
  Si el número cambia, que sea por tests agregados o quitados a propósito.
- Chequeo de versiones nuevas de los XSD en la SET (hace red; se corre a mano
  o desde el job semanal del workflow):
  `CHECK_SCHEMA_UPDATES=1 python -m pytest tests/test_schema_versions.py::TestSchemaUpdates`.

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
`python -m kilasifen.infrastructure.jobs.outbox_worker`.

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
- **Compatibilidad.** El engine declara Python 3.10 como mínimo, así que dentro
  de `kilasifen/engine` no se usan `datetime.UTC`, `typing.Self`, `tomllib` ni
  otras APIs 3.11+. Ojo: hoy nadie lo verifica en 3.10 (el entorno local usa
  3.14 y el CI nunca completó una corrida).
- **Firma.** `sdk/signer.py` implementa la firma *enveloped* RSA-SHA256 (C14N
  exclusiva, digest SHA-256, sin prefijo `ds:`) y guarda en una caché LRU los
  firmadores PKCS#12 ya decodificados. `firma.sign_xml` es la entrada pública:
  la usan `BindingMixin.sign_xml` y `infrastructure/sifen/engine.py`.
  `TransmisionBase` y `infrastructure/sifen/typed_event_builder.py` piden el
  firmador directamente con `sdk.signer.get_pkcs12_signer`.
- **Transporte.** `TransmisionBase` arma el cliente SOAP con mTLS; endpoints y
  ambientes salen de `transmision/config.py`. La plataforma envía el XML ya
  firmado con `SifenClient.enviar_de_xml` (que delega en
  `TransmisionDE.enviar_de_xml`), no con `enviar_de(rde)`.

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
  layout v141 (ver «Esquemas XSD»).
- **Configuración y secretos.** Todo sale de variables `KILA_SIFEN_*`
  (`kilasifen/config.py`, `.env.example`). CSC, PFX y contraseñas se guardan
  cifrados y las respuestas de la API no los devuelven (el emisor expone
  `csc_configured`, no el CSC). Los logs no deben exponer datos sensibles
  (regla 9 de `AGENTS.md`).
- **Python.** La plataforma usa `datetime.UTC` en 18 módulos, así que en la
  práctica requiere 3.11+, aunque `pyproject.toml` declare `>=3.10`.

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

- `TransmisionDE.enviar_de(rde)` con un XML prefijado por xsdata produce una
  firma inválida (es el xfail estricto). La plataforma usa `enviar_de_xml`.
- `enviar_lote` codifica en base64 dos veces y sin ZIP: no cumple la
  especificación. La plataforma no lo usa.
- Un SOAP Fault o una respuesta ilegible aparece como error de parseo y no
  como error de transporte con resultado incierto.
- La protección contra envíos duplicados depende de `max_retries=0` (valor
  por defecto).
- `consultar_dte_async` se reintenta como si fuera una consulta de solo
  lectura.
- El único binding `RDe` tiene el layout v141 (sin `dSisFact`).

Plataforma (hallazgos de auditoría pendientes):

- `codigo_seguridad` toma por defecto la constante `123456789`.
- Dirección, teléfono, email y actividad del emisor reciben valores ficticios
  si faltan en el payload.
- El QR de producción usa siempre el parámetro `dRucRec`.
- Al clasificar la respuesta de un DE (`infrastructure/sifen/engine.py`), un
  código distinto de `0260` se marca como rechazo salvo que `dEstRes` diga
  «Aprobado» sin más texto; no se produce el estado «aprobado con
  observación».
- Un documento cuyo envío falló antes de llegar al SIFEN puede quedar trabado
  en `reconciliation_required`.

Proyecto:

- `requires-python = ">=3.10"` no refleja que la plataforma necesita 3.11+.
  Por la misma razón, en 3.10 `tests/test_logging.py` y
  `tests/test_observability.py` fallarían al importar `kilasifen.logging`, y
  el job `engine-regressions` del CI los incluye en su matriz 3.10.
- `tests/test_ares_de_test_xml.py` ejercita
  `docs/examples/send_ares_factura_test.py`, que trae RUC, razón social y
  timbrado con aspecto de datos reales de un contribuyente; el certificado
  efímero de `conftest.py` usa ese mismo RUC. Hay que pasarlos a datos
  ficticios.
- El workflow `.github/workflows/tests.yml` (push/PR a `main` y semanal) nunca
  completó una corrida por fallas de arranque a nivel de cuenta. No afirmar
  que el CI está en verde: validar localmente.
