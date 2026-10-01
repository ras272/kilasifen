# Matriz de trazabilidad normativa

Objetivo: mantener una trazabilidad simple entre la norma oficial, la regla tecnica aplicada y la evidencia en codigo/tests.

## Matriz

| area/feature | regla tecnica | fuente oficial | evidencia en codigo/tests | estado |
| --- | --- | --- | --- | --- |
| Estructura de DE v150 | Usar el arbol y tipos definidos por el schema v150 para construir y validar los documentos DE. | Manual v150, XSD `DE_v150.xsd`, `DE_Types_v150.xsd` | `kilasifen/engine/de/bindings/v150/de_v150.py`, `kilasifen/engine/de/bindings/v150/de_types_v150.py`, `kilasifen/infrastructure/sifen/typed_xml_builder.py`, `kilasifen/engine/sdk/validation.py`, `tests/test_generate_de.py`, `tests/infrastructure/test_typed_xml_builder.py` | implementado (ver nota 1) |
| Campos catalogados | Respetar catalogos oficiales para paises, unidades y departamentos en la serializacion y validacion. | Manual v150, XSD `Paises_v100.xsd`, `Unidades_Medida_v141.xsd`, `Departamentos_v141.xsd` | `kilasifen/engine/de/bindings/v150/paises_v100.py`, `kilasifen/engine/de/bindings/v150/unidades_medida_v141.py`, `kilasifen/engine/de/bindings/v150/departamentos_v141.py`, `tests/test_schema_versions.py` | implementado |
| Firma XML | Firmar el documento con XMLDSig conforme al esquema y perfiles soportados por SIFEN. | Manual v150, XSD `xmldsig-core-schema.xsd` | `kilasifen/engine/firma.py`, `kilasifen/engine/sdk/signer.py`, `kilasifen/engine/de/bindings/v150/xmldsig_core_schema.py`, `tests/test_firma_xmldsig.py`, `tests/test_firma.py` | implementado |
| Transmision DE | Construir y enviar el DE usando el contrato SOAP definido por el schema del servicio. | Manual v150, XSD `siRecepDE_v150.xsd`, `protProcesDE_v150.xsd`, `WS_SiRecepDE_v150.xsd` | `kilasifen/engine/transmision/de.py`, `kilasifen/engine/transmision/base.py`, `kilasifen/infrastructure/sifen/engine.py`, `tests/test_transmision.py`, `tests/infrastructure/test_sifen_engine.py` | implementado (ver nota 2) |
| Transmision evento | Construir y enviar eventos con el contrato SOAP correspondiente a eventos. | Manual v150, XSD `siRecepEvento_v150.xsd`, `Evento_v150.xsd`, `Evento_Types_v150.xsd` | `kilasifen/engine/transmision/evento.py`, `kilasifen/infrastructure/sifen/typed_event_builder.py`, `kilasifen/infrastructure/sifen/event.py`, `kilasifen/engine/de/bindings/v150/evento_v150.py`, `kilasifen/engine/de/bindings/v150/evento_types_v150.py`, `tests/test_transmision.py`, `tests/test_eventos.py`, `tests/infrastructure/test_sifen_event_gateway.py` | implementado |
| Consulta SIFEN | Consumir servicios de consulta con las operaciones y respuestas previstas por el schema. | Manual v150, XSD `WS_SiConsDTE.xsd`, `WS_SiConsDTEAsync.xsd`, `WS_SiConsLote_v141.xsd`, `WS_SiConsRUC_v141.xsd` | `kilasifen/engine/transmision/consulta.py`, `kilasifen/infrastructure/sifen/query.py`, `tests/test_transmision.py`, `tests/test_ws.py` | parcial |
| Versiones de schema | Detectar cambios locales vs remotos sin tocar artefactos generados. | XSD publicados por SET, baseline local en repo | `tests/test_schema_versions.py` | implementado |
| Integridad de schemas | Verificar que los XSD requeridos existan y no apunten a ubicaciones remotas. | XSD local versionado | `tests/test_schema_versions.py` | implementado |
| Reenvío incierto de DE | Nunca reenviar un CDC sin resultado definitivo; ante falta de respuesta, consultar por CDC y reutilizar el payload exacto. | Guía DNIT de mejores prácticas para gestión del envío de DE (octubre 2024) | `kilasifen/infrastructure/jobs/document_attempts.py`, `kilasifen/infrastructure/jobs/workers.py`, `tests/application/test_emission_flow.py`, `tests/application/test_document_attempt_transactions.py` | implementado |
| Recibo Electrónico de Dinero | No presentar `iTiDE=8` como Recibo ni habilitar transmisión hasta contar con formato/validaciones oficiales completos. | Decreto 872/2023; Manual 150; `siRecepRDE_v150.xsd` publicado por DNIT | `docs/architecture/adr-0002-recibo-electronico.md` | pendiente de DNIT |

Nota 1: el unico binding `RDe` generado proviene de `FE_v141.xsd` (`kilasifen/engine/de/bindings/v150/fe_v141.py`) y conserva la estructura v141, sin `dSisFact`; los tests de muestras y de generacion lo usan. La emision de la plataforma no pasa por ese binding: `kilasifen/infrastructure/sifen/typed_xml_builder.py` arma el XML y lo valida contra `siRecepDE_v150.xsd` antes de firmar.

Nota 2: lo implementado es el envio individual de un `rEnviDe` armado con `_build_enviar_de_request_xml` (el mismo que usa `TransmisionDE.enviar_de_xml`); la plataforma lo guarda antes de enviarlo y lo transmite tal cual con `TransmisionDE._send_raw_xml`. `enviar_lote` no respeta el formato del servicio de lotes (base64 doble, sin ZIP) y `enviar_de(rde)` con firma envia una firma que no verifica; ambos defectos se conservaron a proposito y estan descritos en `docs/architecture/public-api.md` (seccion Problemas conocidos).

## Proceso de actualizacion cuando cambien NT o XSD

1. Identificar el cambio oficial: nueva NT, correccion de manual, o nueva version de XSD.
2. Registrar el impacto por area/feature en esta matriz.
3. Actualizar o agregar la evidencia en `tests/`, `kilasifen/engine/` o `kilasifen/infrastructure/sifen/` si la regla cambia.
4. Mantener intactos los bindings generados salvo una regeneracion controlada y justificada con `scripts/generate_bindings.py`; `python scripts/generate_bindings.py --check` confirma que no hay deriva.
5. Ejecutar la suite minima que cubre la regla afectada.
6. Marcar el estado correcto: `implementado`, `parcial` o `pendiente`.
7. Dejar referencia del cambio en el commit o PR para auditoria futura.

## Criterio de uso

- Si la fuente oficial cambia y no existe prueba asociada, el estado debe quedar en `parcial` o `pendiente`.
- Si la regla vive en codigo pero no tiene test, agregar el test antes de marcarla como `implementado`.
- Esta matriz debe ser breve y mantenerse actualizada junto con los cambios normativos.
