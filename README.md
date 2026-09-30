# KilaSifen

API fiscal headless para conectar cualquier ERP, comercio o producto con
**SIFEN Paraguay** sin implementar XML, firma, SOAP, reintentos ni
reconciliación fiscal dentro del sistema consumidor.

- contratos tipados para factura, nota de crédito y nota de débito;
- emisión asíncrona, idempotencia estricta y numeración atómica;
- cancelación, inutilización, consultas, KuDE y webhooks HMAC;
- aislamiento por consumidor, secretos cifrados y sandbox determinista;
- SDK TypeScript oficial en [`sdks/typescript`](sdks/typescript).

El contrato HTTP y las guías de conexión viven en el portal Fumadocs de
[`apps/docs`](apps/docs) y en [`docs/INTEGRATION.md`](docs/INTEGRATION.md).

## Motor Python

El mismo repositorio incluye los bindings Python que leen, generan, validan,
firman y transmiten XML SIFEN v150. La API usa ese motor internamente, pero los
integradores pueden consumirla sin importar código Python ni conocer SOAP.

Generados automáticamente a partir de los XSD oficiales de la SET usando [xsdata](https://xsdata.readthedocs.io/), siguiendo el mismo enfoque de [nfelib](https://github.com/akretion/nfelib).

## Instalación

```bash
pip install kilasifen
```

Con firma digital (RSA-SHA256):

```bash
pip install kilasifen[sign]
```

Con transmisión SOAP (envío al SIFEN):

```bash
pip install kilasifen[transmissao]
```

Para desarrollo:

```bash
pip install -e ".[sign,test]"
```

## Uso

### Fachada pública estable

```python
from kilasifen.engine import (
    ConsultaSIFEN,
    PRODUCCION,
    TEST,
    TransmissaoDE,
    TransmissaoEvento,
    get_endpoint,
    sign_xml,
)
```

Esta es la forma recomendada de consumir la librería para código de aplicación. La fachada top-level mantiene los imports más usados en un solo lugar y evita depender de la estructura interna del paquete.

### Ejemplos ejecutables

- [Envio sincrono de factura](docs/examples/send_factura_sync.py)
- [Envio de lote](docs/examples/send_lote.py)

Estos scripts estan pensados para copiar/ejecutar con un certificado PKCS12 y XMLs DE listos.


```python
from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

# Leer desde archivo
rde = RDe.from_path("factura.xml")

# Leer desde string
rde = RDe.from_xml(xml_string)

# Navegar los datos
print(rde.DE.gDatGralOpe.gEmis.dRucEm)       # RUC del emisor
print(rde.DE.gDatGralOpe.gEmis.dNomEmi)       # Nombre del emisor
print(rde.DE.gDtipDE.gCamFE.iIndPres)         # Indicador de presencia
print(len(rde.DE.gDtipDE.gCamItem))            # Cantidad de ítems
```

### Serializar a XML

```python
xml = rde.to_xml()
print(xml)
```

### Round-trip (leer y escribir)

```python
rde = RDe.from_path("factura.xml")
xml = rde.to_xml()
rde2 = RDe.from_xml(xml)
assert rde.DE.Id == rde2.DE.Id
```

### Validar contra XSD

```python
errors = rde.validate_xml()
if not errors:
    print("XML válido!")
else:
    for error in errors:
        print(error)
```

### Firmar XML (RSA-SHA256)

```bash
pip install kilasifen[sign]
```

```python
with open("certificado.pfx", "rb") as f:
    cert_data = f.read()
signed = rde.sign_xml(xml, cert_data, "password", rde.DE.Id)
```

Usa `signxml` directamente con RSA-SHA256 y C14N, conforme lo exigido por el SIFEN.
La función centralizada también está disponible en:

```python
from kilasifen.engine.firma import sign_xml

signed = sign_xml(xml, cert_data, "password", doc_id)
```

### Generar CDC (SIFEN v150)

```python
from kilasifen.engine.sdk import generate_cdc

cdc = generate_cdc(
    i_tide=1,
    d_ruc_em="44444401",
    d_dv_emi=7,
    d_est="001",
    d_pun_exp="001",
    d_num_doc="14528",
    i_tip_cont=2,
    d_fe_emi_de="2017-01-25T15:58:17",
    i_tip_emi=1,
    d_cod_seg="587326098",
)
# 01444444017001001001452822017012515873260988
```

El dígito verificador del CDC se calcula con módulo 11 conforme a la guía
oficial de SET/DNIT.

### Generar dCarQR (SIFEN v150)

```python
from kilasifen.engine.sdk import generate_dcarqr

dcarqr = generate_dcarqr(
    cdc="01444444017001001001452822017012515873260988",
    d_fe_emi_de="2017-01-25T09:35:17",
    digest_value="yzGYhUx1/XYYzksWB+fPR3Qc50c=",
    id_csc="0001",
    csc="ABCD0000000000000000000000000000",
    d_ruc_rec="88899990",
    d_tot_gral_ope="300000",
    d_tot_iva="27272",
    c_items=2,
)
```

Para insertar en XML con escape HTML (`&amp;`) usa:

```python
dcarqr_xml = generate_dcarqr(..., xml_escaped=True)
```

### Transmisión SOAP al SIFEN

```bash
pip install kilasifen[transmissao]
```

#### Enviar DE (síncrono)

```python
from kilasifen.engine.transmissao import TransmissaoDE, TEST

transmissao = TransmissaoDE(
    ambiente=TEST,
    pkcs12_data=cert_data,
    pkcs12_password="password",
)
resultado = transmissao.enviar_de(rde)
print(resultado.rProtDe.dEstRes)      # "Aprobado"
print(resultado.rProtDe.dProtAut)     # Protocolo de autorización
```

#### Enviar lote de DEs (asíncrono)

```python
resultado = transmissao.enviar_lote([rde1, rde2, rde3])
print(resultado.dProtConsLote)  # Protocolo para consulta posterior
```

#### Consultar DE por CDC

```python
from kilasifen.engine.transmissao import ConsultaSIFEN, TEST

consulta = ConsultaSIFEN(
    ambiente=TEST,
    pkcs12_data=cert_data,
    pkcs12_password="password",
)
resultado = consulta.consultar_de("01800695631001001000000612024112917595714694")
```

#### Consultar RUC

```python
resultado = consulta.consultar_ruc("80069563")
print(resultado.xContRUC.dRazCons)      # Razón social
print(resultado.xContRUC.dRUCFactElec)  # "S" = habilitado para FE
```

#### Consultar DTE async (inicio + polling)

```python
respuesta_async = consulta.consultar_dte_async(consulta_dte_async)
protocolo = respuesta_async.dProtConsDTEAsync

# Opcional: esperar estado final con helper de polling
from kilasifen.engine.sdk import PollingConfig, poll_dte_async_status

estado_final = poll_dte_async_status(
    fetch_status=mi_funcion_de_estado,  # callback(protocol_id) -> response
    protocol_id=protocolo,
    config=PollingConfig(interval_seconds=2, timeout_seconds=120),
)
```

#### Enviar eventos (cancelación, inutilización, etc.)

```python
from kilasifen.engine.transmissao import TransmissaoEvento, TEST

evento_transmissao = TransmissaoEvento(
    ambiente=TEST,
    pkcs12_data=cert_data,
    pkcs12_password="password",
)
resultado = evento_transmissao.enviar_evento(evento)
```

### Integración rápida con SifenClient

```python
from kilasifen.engine.sdk.client import SifenClient

client = SifenClient(
    ambiente=TEST,
    pkcs12_data=cert_data,
    pkcs12_password="password",
)

# Wrappers de núcleo fiscal
cdc = client.generar_cdc(...)
dcarqr = client.generar_dcarqr(...)

# Envío de lote + espera con polling en una llamada
estado_lote = client.enviar_lote_y_esperar([rde1, rde2], sign=True)

# Consulta DTE async + espera con polling en una llamada
solicitud, estado = client.consultar_dte_async_y_esperar(
    consulta_dte_async=consulta_dte_async,
    fetch_status=mi_funcion_de_estado,
)
```

### KuDE HTML (salida imprimible v1)

```python
from kilasifen.engine.sdk import render_kude_html, save_kude_html

html = render_kude_html(rde, title="KuDE Factura")
save_kude_html(rde, "outputs/kude_factura.html", title="KuDE Factura")
```

Con `SifenClient`:

```python
html = client.render_kude_html(rde, title="KuDE Factura")
client.save_kude_html(rde, "outputs/kude_factura.html")
```

## Tipos de Documento Electrónico

| Tipo | Código | Descripción |
|------|--------|-------------|
| Factura Electrónica | 1 | Factura electrónica estándar |
| FE Exportación | 2 | Factura de exportación |
| FE Importación | 3 | Factura de importación |
| Autofactura | 4 | Autofactura |
| Nota de Crédito | 5 | Nota de crédito electrónica |
| Nota de Débito | 6 | Nota de débito electrónica |
| Nota de Remisión | 7 | Nota de remisión electrónica |
| Comprobante de Retención | 8 | Comprobante de retención |

## Módulos

### Bindings (generados automáticamente)

| Módulo | Descripción |
|--------|-------------|
| `fe_v141` | Documento Electrónico principal (RDe, TDe, TgEmis, ...) |
| `de_v150` | Tipos adicionales del DE v150 |
| `de_types_v150` | Tipos base (enums, restricciones) |
| `evento_v150` | Eventos (cancelación, inutilización, conformidad, ...) |
| `evento_types_v150` | Tipos de eventos |
| `ws_si_recep_de_v150` | WS Recepción DE |
| `ws_si_recep_evento_v150` | WS Recepción Evento |
| `ws_si_cons_de_v141` | WS Consulta DE |
| `ws_si_cons_ruc_v141` | WS Consulta RUC |
| `prot_proces_de_v150` | Protocolo de procesamiento |
| `xmldsig_core_schema` | Firma digital XML |

### Firma (`kilasifen.engine.firma`)

| Función | Descripción |
|---------|-------------|
| `sign_xml()` | Firma XML con PKCS12/RSA-SHA256 usando `signxml` |

### Transmisión (`kilasifen.engine.transmissao`)

| Clase | Descripción |
|-------|-------------|
| `TransmissaoDE` | Envío de DEs (síncrono y lote) con mTLS |
| `ConsultaSIFEN` | Consultas (DE por CDC, lote, RUC, DTE) |
| `TransmissaoEvento` | Envío de eventos (cancelación, inutilización, etc.) |
| `TransmissaoBase` | Clase base con SOAP client, mTLS y serialización |

### Ambientes

| Constante | Valor | Descripción |
|-----------|-------|-------------|
| `PRODUCCION` | 1 | Ambiente de producción (`sifen.set.gov.py`) |
| `TEST` | 2 | Ambiente de pruebas (`sifen-test.set.gov.py`) |

## Dependencias Opcionales

| Extra | Paquetes | Uso |
|-------|----------|-----|
| `sign` | `signxml`, `cryptography`, `lxml` | Firma digital RSA-SHA256 |
| `transmissao` | `xsdata[soap]`, `signxml`, `cryptography`, `requests`, `lxml` | Transmisión SOAP con mTLS |
| `soap` | `xsdata[soap]` | Solo cliente SOAP |
| `test` | `pytest`, `pytest-cov`, `xmldiff`, `lxml` | Tests |

## Regenerar Bindings

Si los XSD se actualizan:

```bash
pip install xsdata[cli,lxml]
./script.sh
```

## Desarrollo

```bash
git clone https://github.com/ras272/kilasifen.git
cd kilasifen
python -m venv .venv
source .venv/bin/activate
pip install -e ".[sign,test]" "xsdata[cli,lxml]"
pytest tests/ -v
ruff check kilasifen/engine/ tests/
```

## Referencias

- [XSD oficiales SIFEN](https://ekuatia.set.gov.py/sifen/xsd/)
- [Manual Técnico v150](https://www.dnit.gov.py/documents/20123/420592/Manual+T%C3%A9cnico+Versi%C3%B3n+150.pdf)
- [Portal e-Kuatia](https://ekuatia.set.gov.py)
- [nfelib (referencia)](https://github.com/akretion/nfelib)
- [xsdata](https://xsdata.readthedocs.io/)

## Kila SIFEN Platform (API)

This repository contains four complementary components:

- `kilasifen.engine`: fiscal engine (XML, signature, SOAP transport)
- `kilasifen`: headless, multi-consumer API platform for independent SIFEN integrations
- `sdks/typescript`: official typed client for the HTTP API
- `apps/docs`: public Fumadocs integration portal

Platform docs:

- `docs/architecture/current-scope.md`
- `docs/architecture/kila-platform.md`
- `docs/operations/deployment-compose.md`
- `docs/operations/job-lifecycle.md`
- `docs/integrations/webhooks.md`
- `docs/examples/kila_api_register_certificate.py`
- `docs/examples/kila_api_emit_document.py`

Current platform scope in one line:

- consumer-neutral HTTP integration surface
- multiple isolated consumers and SIFEN emitters
- strict emitter isolation
- PDF + JSON KuDE support
- typed Factura, Nota de Crédito and Nota de Débito builders
- typed cancel/inutilization events
- durable outbox, safe reconciliation and deterministic sandbox outcomes

Local platform stack:

```bash
cp .env.example .env
docker compose up -d --build
```

## Comunidad y OSS

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Security Policy](SECURITY.md)

## Licencia

MIT License - Copyright (c) KMEE

