# Matriz de trazabilidad normativa

Objetivo: mantener una trazabilidad simple entre la norma oficial, la regla tecnica aplicada y la evidencia en codigo/tests.

## Matriz

| area/feature | regla tecnica | fuente oficial | evidencia en codigo/tests | estado |
| --- | --- | --- | --- | --- |
| Estructura de DE v150 | Usar el arbol y tipos definidos por el schema v150 para construir y validar los documentos DE. | Manual v150, XSD `DE_v150.xsd`, `DE_Types_v150.xsd` | `pysifen/de/bindings/v150/de_v150.py`, `pysifen/de/bindings/v150/de_types_v150.py`, `tests/test_generate_de.py` | implementado |
| Campos catalogados | Respetar catalogos oficiales para paises, unidades y departamentos en la serializacion y validacion. | Manual v150, XSD `Paises_v100.xsd`, `Unidades_Medida_v141.xsd`, `Departamentos_v141.xsd` | `pysifen/de/bindings/v150/paises_v100.py`, `pysifen/de/bindings/v150/unidades_medida_v141.py`, `pysifen/de/bindings/v150/departamentos_v141.py`, `tests/test_schema_versions.py` | implementado |
| Firma XML | Firmar el documento con XMLDSig conforme al esquema y perfiles soportados por SIFEN. | Manual v150, XSD `xmldsig-core-schema.xsd` | `pysifen/assinatura.py`, `pysifen/de/bindings/v150/xmldsig_core_schema.py`, `tests/test_assinatura.py` | implementado |
| Transmision DE | Construir y enviar el DE usando el contrato SOAP definido por el schema del servicio. | Manual v150, XSD `siRecepDE_v150.xsd`, `protProcesDE_v150.xsd`, `WS_SiRecepDE_v150.xsd` | `pysifen/transmissao/de.py`, `pysifen/transmissao/base.py`, `tests/test_transmissao.py` | implementado |
| Transmision evento | Construir y enviar eventos con el contrato SOAP correspondiente a eventos. | Manual v150, XSD `siRecepEvento_v150.xsd`, `Evento_v150.xsd`, `Evento_Types_v150.xsd` | `pysifen/transmissao/evento.py`, `pysifen/de/bindings/v150/evento_v150.py`, `pysifen/de/bindings/v150/evento_types_v150.py`, `tests/test_eventos.py` | implementado |
| Consulta SIFEN | Consumir servicios de consulta con las operaciones y respuestas previstas por el schema. | Manual v150, XSD `WS_SiConsDTE.xsd`, `WS_SiConsDTEAsync.xsd`, `WS_SiConsLote_v141.xsd`, `WS_SiConsRUC_v141.xsd` | `pysifen/transmissao/consulta.py`, `tests/test_ws.py` | parcial |
| Versiones de schema | Detectar cambios locales vs remotos sin tocar artefactos generados. | XSD publicados por SET, baseline local en repo | `tests/test_schema_versions.py` | implementado |
| Integridad de schemas | Verificar que los XSD requeridos existan y no apunten a ubicaciones remotas. | XSD local versionado | `tests/test_schema_versions.py` | implementado |

## Proceso de actualizacion cuando cambien NT o XSD

1. Identificar el cambio oficial: nueva NT, correccion de manual, o nueva version de XSD.
2. Registrar el impacto por area/feature en esta matriz.
3. Actualizar o agregar la evidencia en `tests/` o `pysifen/` si la regla cambia.
4. Mantener intactos los bindings generados salvo una regeneracion controlada y justificada.
5. Ejecutar la suite minima que cubre la regla afectada.
6. Marcar el estado correcto: `implementado`, `parcial` o `pendiente`.
7. Dejar referencia del cambio en el commit o PR para auditoria futura.

## Criterio de uso

- Si la fuente oficial cambia y no existe prueba asociada, el estado debe quedar en `parcial` o `pendiente`.
- Si la regla vive en codigo pero no tiene test, agregar el test antes de marcarla como `implementado`.
- Esta matriz debe ser breve y mantenerse actualizada junto con los cambios normativos.
