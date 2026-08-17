# ADR-0002: Recibo Electrónico de Dinero

- Estado: aceptado
- Fecha: 2026-08-17

## Contexto

El producto necesita soportar Recibo Electrónico de Dinero (RDE). El Decreto
872/2023 lo define como el documento para cuotas de operaciones a crédito/plazo
o ingresos donde no corresponde emitir otro documento tributario. Si documenta
una cuota, debe asociarse a la Factura Electrónica.

La documentación técnica vigente no permite una implementación fiscal segura:

- el Manual Técnico 150 enumera `iTiDE=8` como Comprobante de Retención
  Electrónico (futuro), no como Recibo;
- el Manual 150 no contiene una tabla completa de campos/validaciones de RDE;
- el XSD oficial `siRecepRDE_v150.xsd` incluye
  `rde/150/RDE_Group.xsd`, pero esa dependencia devuelve HTTP 404 al
  2026-08-17;
- la DNIT comunicó en octubre de 2025 que el Recibo de Dinero Electrónico seguía
  entre los proyectos normativos bajo revisión.

Fuentes oficiales:

- https://www.dnit.gov.py/web/e-kuatia/documentacion-tecnica
- https://www.dnit.gov.py/documents/20123/420592/Manual+T%C3%A9cnico+Versi%C3%B3n+150.pdf/e706f7c7-6d93-21d4-b45b-5d22d07b2d22
- https://ekuatia.set.gov.py/sifen/xsd/siRecepRDE_v150.xsd
- https://www.dnit.gov.py/documents/20123/559197/Decreto+N%C2%B0+872-23.pdf/c86edb49-54e2-367c-8626-13390cea60b1

## Decisión

KilaSifen no expondrá un endpoint que afirme transmitir RDE a SIFEN mientras la
estructura oficial completa no sea obtenible y validable. Tampoco reutilizará
`iTiDE=8` para Recibo.

Un recibo comercial interno sólo podrá agregarse como recurso explícitamente no
fiscal y no transmitido, mediante una decisión de producto separada.

## Condición de habilitación

Para habilitar RDE fiscal se requiere, como mínimo:

1. XSD oficial autocontenido o paquete oficial con todas sus dependencias.
2. Tabla oficial de campos, reglas de validación y códigos de respuesta.
3. WSDL/endpoints de test y producción publicados.
4. XML de ejemplo o guía de pruebas oficial.
5. Golden tests, firma, consulta, KuDE/representación y evidencia en ambiente de
   test antes de habilitar producción.
