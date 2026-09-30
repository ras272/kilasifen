# Estado Actual: Debugging SIFEN TEST

Fecha: `2026-04-24`

## Punto actual

La integracion Python todavia no logra pasar el error `2500 - calculo-coincide-info-xml` en `SIFEN TEST`, pero el problema ya quedo acotado con evidencia fuerte.

## Lo que ya esta probado

- El certificado `F1T_49592.p12` funciona en TEST.
- `consultar_ruc("80024135")` funciona.
- El timbrado de TEST que estamos usando para ARES es:
  - `dNumTim=80024135`
  - `dFeIniT=2024-03-11`
- El XML Python de prueba:
  - valida contra `siRecepDE_v150.xsd`
  - reconstruye el `dCarQR` exactamente igual al que trae el XML firmado
- Se agrego una herramienta de reporte:
  - [debug_qr_report.py](/C:/Users/jaack/Desktop/kilasifen/docs/examples/debug_qr_report.py)
  - confirma localmente `schema_valid=True` y `dcarqr_matches_rebuilt=True`

## Prueba externa con la libreria de Roshka

Se clono `rshk-jsifenlib` en una carpeta temporal fuera del repo principal y se ejecuto un runner minimo con:

- mismo certificado de ARES
- mismo ambiente `DEV/TEST`
- mismo `IdCSC=0001`
- mismo `CSC=ABCD0000000000000000000000000000`

Resultado real de la emision Java:

- `consultaRUC`: funciona
- `recepcionDE`: llega a `https://sifen-test.set.gov.py/de/ws/sync/recibe.wsdl`
- respuesta: `1002 | Documento electrónico duplicado`

Esto prueba que:

- el ambiente TEST responde correctamente
- el certificado y el CSC generico TEST no son el bloqueo principal
- la validacion QR/XML si puede pasar usando una implementacion de referencia

## Cambios aplicados en PySIFEN

- El signer de Python fue alineado a `exclusive c14n`:
  - [signer.py](/C:/Users/jaack/Desktop/kilasifen/kilasifen/engine/sdk/signer.py)
- El ejemplo ARES TEST fue acercado a la salida lexical de Roshka:
  - montos enteros
  - `iTiContRec=2`
  - grupo `gTotSub` mas cercano a la forma emitida por Java
  - orden de `gValorRestaItem` corregido para salir del `0160 XML malformado`

## Estado exacto despues de esos cambios

- PySIFEN ya salio temporalmente de `0160 XML malformado`
- pero el envio actual de Python vuelve a:
  - `2500 - calculo-coincide-info-xml`

## Conclusión tecnica

El problema ya no parece estar en:

- certificado
- ambiente TEST
- timbrado de prueba usado
- construccion basica del `dCarQR`

El sospechoso principal ahora es la diferencia entre el XML firmado que genera Python y el XML firmado que genera la libreria Java de Roshka.

## Siguiente paso correcto

Comparar lado a lado el `rDE` firmado de:

1. PySIFEN
2. Roshka

En especial:

- `SignedInfo`
- `Reference`
- `Transforms`
- `DigestValue`
- orden final de nodos firmados
- forma lexical exacta de montos y campos del item

Objetivo:

Replicar en Python la salida firmada de Roshka, no seguir ajustando campos al azar.
