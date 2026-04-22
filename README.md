# kilasifen

Bindings Python para leer y generar XML del **SIFEN** (Sistema Integrado de FacturaciÃ³n ElectrÃ³nica Nacional) de Paraguay.

Generados automÃ¡ticamente a partir de los XSD oficiales de la SET usando [xsdata](https://xsdata.readthedocs.io/), siguiendo el mismo enfoque de [nfelib](https://github.com/akretion/nfelib).

## InstalaciÃ³n

```bash
pip install kilasifen
```

Con firma digital (RSA-SHA256):

```bash
pip install kilasifen[sign]
```

Con transmisiÃ³n SOAP (envÃ­o al SIFEN):

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
from pysifen import (
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


```python
from pysifen.de.bindings.v150.fe_v141 import RDe

# Leer desde archivo
rde = RDe.from_path("factura.xml")

# Leer desde string
rde = RDe.from_xml(xml_string)

# Navegar los datos
print(rde.DE.gDatGralOpe.gEmis.dRucEm)       # RUC del emisor
print(rde.DE.gDatGralOpe.gEmis.dNomEmi)       # Nombre del emisor
print(rde.DE.gDtipDE.gCamFE.iIndPres)         # Indicador de presencia
print(len(rde.DE.gDtipDE.gCamItem))            # Cantidad de Ã­tems
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
    print("XML vÃ¡lido!")
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
La funciÃ³n centralizada tambiÃ©n estÃ¡ disponible en:

```python
from pysifen.assinatura import sign_xml

signed = sign_xml(xml, cert_data, "password", doc_id)
```

### TransmisiÃ³n SOAP al SIFEN

```bash
pip install kilasifen[transmissao]
```

#### Enviar DE (sÃ­ncrono)

```python
from pysifen.transmissao import TransmissaoDE, TEST

transmissao = TransmissaoDE(
    ambiente=TEST,
    pkcs12_data=cert_data,
    pkcs12_password="password",
)
resultado = transmissao.enviar_de(rde)
print(resultado.rProtDe.dEstRes)      # "Aprobado"
print(resultado.rProtDe.dProtAut)     # Protocolo de autorizaciÃ³n
```

#### Enviar lote de DEs (asÃ­ncrono)

```python
resultado = transmissao.enviar_lote([rde1, rde2, rde3])
print(resultado.dProtConsLote)  # Protocolo para consulta posterior
```

#### Consultar DE por CDC

```python
from pysifen.transmissao import ConsultaSIFEN, TEST

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
print(resultado.xContRUC.dRazCons)      # RazÃ³n social
print(resultado.xContRUC.dRUCFactElec)  # "S" = habilitado para FE
```

#### Enviar eventos (cancelaciÃ³n, inutilizaciÃ³n, etc.)

```python
from pysifen.transmissao import TransmissaoEvento, TEST

evento_transmissao = TransmissaoEvento(
    ambiente=TEST,
    pkcs12_data=cert_data,
    pkcs12_password="password",
)
resultado = evento_transmissao.enviar_evento(evento)
```

## Tipos de Documento ElectrÃ³nico

| Tipo | CÃ³digo | DescripciÃ³n |
|------|--------|-------------|
| Factura ElectrÃ³nica | 1 | Factura electrÃ³nica estÃ¡ndar |
| FE ExportaciÃ³n | 2 | Factura de exportaciÃ³n |
| FE ImportaciÃ³n | 3 | Factura de importaciÃ³n |
| Autofactura | 4 | Autofactura |
| Nota de CrÃ©dito | 5 | Nota de crÃ©dito electrÃ³nica |
| Nota de DÃ©bito | 6 | Nota de dÃ©bito electrÃ³nica |
| Nota de RemisiÃ³n | 7 | Nota de remisiÃ³n electrÃ³nica |
| Comprobante de RetenciÃ³n | 8 | Comprobante de retenciÃ³n |

## MÃ³dulos

### Bindings (generados automÃ¡ticamente)

| MÃ³dulo | DescripciÃ³n |
|--------|-------------|
| `fe_v141` | Documento ElectrÃ³nico principal (RDe, TDe, TgEmis, ...) |
| `de_v150` | Tipos adicionales del DE v150 |
| `de_types_v150` | Tipos base (enums, restricciones) |
| `evento_v150` | Eventos (cancelaciÃ³n, inutilizaciÃ³n, conformidad, ...) |
| `evento_types_v150` | Tipos de eventos |
| `ws_si_recep_de_v150` | WS RecepciÃ³n DE |
| `ws_si_recep_evento_v150` | WS RecepciÃ³n Evento |
| `ws_si_cons_de_v141` | WS Consulta DE |
| `ws_si_cons_ruc_v141` | WS Consulta RUC |
| `prot_proces_de_v150` | Protocolo de procesamiento |
| `xmldsig_core_schema` | Firma digital XML |

### Firma (`pysifen.assinatura`)

| FunciÃ³n | DescripciÃ³n |
|---------|-------------|
| `sign_xml()` | Firma XML con PKCS12/RSA-SHA256 usando `signxml` |

### TransmisiÃ³n (`pysifen.transmissao`)

| Clase | DescripciÃ³n |
|-------|-------------|
| `TransmissaoDE` | EnvÃ­o de DEs (sÃ­ncrono y lote) con mTLS |
| `ConsultaSIFEN` | Consultas (DE por CDC, lote, RUC, DTE) |
| `TransmissaoEvento` | EnvÃ­o de eventos (cancelaciÃ³n, inutilizaciÃ³n, etc.) |
| `TransmissaoBase` | Clase base con SOAP client, mTLS y serializaciÃ³n |

### Ambientes

| Constante | Valor | DescripciÃ³n |
|-----------|-------|-------------|
| `PRODUCCION` | 1 | Ambiente de producciÃ³n (`sifen.set.gov.py`) |
| `TEST` | 2 | Ambiente de pruebas (`sifen-test.set.gov.py`) |

## Dependencias Opcionales

| Extra | Paquetes | Uso |
|-------|----------|-----|
| `sign` | `signxml`, `cryptography`, `lxml` | Firma digital RSA-SHA256 |
| `transmissao` | `xsdata[soap]`, `signxml`, `cryptography`, `requests`, `lxml` | TransmisiÃ³n SOAP con mTLS |
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
ruff check pysifen/ tests/
```

## Referencias

- [XSD oficiales SIFEN](https://ekuatia.set.gov.py/sifen/xsd/)
- [Manual TÃ©cnico v150](https://www.dnit.gov.py/documents/20123/420592/Manual+T%C3%A9cnico+Versi%C3%B3n+150.pdf)
- [Portal e-Kuatia](https://ekuatia.set.gov.py)
- [nfelib (referencia)](https://github.com/akretion/nfelib)
- [xsdata](https://xsdata.readthedocs.io/)

## Licencia

MIT License - Copyright (c) KMEE

