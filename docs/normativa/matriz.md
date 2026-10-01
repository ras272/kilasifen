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
| Lote asincrono: formato (F65) | `xDE` lleva un ZIP con una sola entrada `.xml`: una unica declaracion UTF-8, `<rLoteDE>` sin namespace y de 1 a 50 `rDE` sin declaracion propia, cada uno con su `xmlns` (y `xsi:schemaLocation`), sin blancos entre etiquetas; el ZIP se codifica en base64 una sola vez (el binding lo hace). | MT v150 §7.2.1 (p. 30), §7.2.2.2 (pp. 31-32), §7.2.4 (pp. 34-35), §9.2 y Schema 5A (p. 47); Guia de mejores practicas DNIT oct-2024, pp. 4 y 8-9; XSD `WS_SiRecepLoteDE_v141.xsd` (`xDE` base64Binary, application/zip) | `kilasifen/engine/transmision/de.py` (`_build_lote_zip`, `enviar_lote_xml`, `enviar_lote`), `tests/test_transmision.py` (`TestLoteFormatoOficial`, `TestTransmisionDE`) | implementado en el engine (la plataforma no envia por lote); ver NO DETERMINADO L1-L5 |
| Lote asincrono: composicion (F65) | Antes de enviar: 1 a 50 DE, un solo `iTiDE`, un solo `dRucEm`, sin CDC repetidos y mensaje de hasta 1000 KB; si no, `ValueError` y no se envia nada. | MT v150 §9.2.1-9.2.2 (p. 47); Guia oct-2024 p. 6 (causas a, b, c y e de 0301) y pp. 6-7 (causas f y g de bloqueo del RUC) | `kilasifen/engine/transmision/de.py` (`_validar_cantidad_lote`, `_validar_composicion_lote`, `_verificar_tamano_mensaje_lote`), `tests/test_transmision.py` | implementado en el engine; ver NO DETERMINADO L4 |
| Consulta de lote (F65) | Por `dProtConsLote` o, si el numero de lote no llego, por un CDC del lote (`dCDC`); exactamente uno de los dos. | MT v150 §9.3.1 (pp. 48-49); XSD `WS_SiConsLote_v141.xsd` (`dCDC` "CDC contenido en un lote"); Guia oct-2024 p. 6, punto 3 | `kilasifen/engine/transmision/consulta.py` (`consultar_lote`), `tests/test_transmision.py` | implementado |
| Espera del resultado del lote (F66) | Solo se consulta tras `0300` con `dProtConsLote` (`0301`: no se consulta). `0361` es el unico pendiente; `0362` es terminal con `gResProcLote` por DE (`dEstRes` normalizado); `0360`, `0363`, `0340` y `0320` son error; con `0364` o mas de 48 h desde la recepcion se consulta cada CDC con siConsDE (`0422` encontrado, `0420` no existe o no aprobado, otro codigo error). Primera consulta a los 600 s e intervalos de 600 s por defecto. | MT v150 Tabla F (p. 49), §9.2.3 (p. 48), §9.3.2 (p. 49), §12.3.2.3 y §12.3.3 (pp. 155-156), Tabla G (p. 51); Guia oct-2024 pp. 6 (punto 4), 9, 10 y 12; XSD `WS_SiConsLote_v141.xsd` | `kilasifen/engine/sdk/polling.py`, `kilasifen/engine/sdk/client.py` (`enviar_lote_y_esperar`), `tests/test_polling.py`, `tests/test_sdk_client.py` | implementado en el engine; ver NO DETERMINADO L6-L7 |
| Consulta DTE sincronica y asincronica (F66) | Marcada experimental: emite `SifenExperimentalWarning`, sus rutas figuran en `SERVICIOS_EXPERIMENTALES` y `poll_dte_async_status` no supone textos de "pendiente". | Solo XSD `WS_SiConsDTE.xsd`, `WS_SiConsDTEAsync.xsd`, `siConsultaDTE.xsd`, `siConsultaDTEAsync.xsd`; ausente de MT v150 §7.10 (p. 41), NT 01-27, Guia oct-2024 p. 5, Guia de pruebas feb-2026 p. 6 y FAQ DNIT | `kilasifen/engine/transmision/config.py`, `kilasifen/engine/transmision/consulta.py`, `kilasifen/engine/sdk/polling.py`, `tests/test_transmision.py`, `tests/test_polling.py` | NO DETERMINADO (experimental); ver L8 |
| Versiones de schema | Detectar cambios locales vs remotos sin tocar artefactos generados. | XSD publicados por SET, baseline local en repo | `tests/test_schema_versions.py` | implementado |
| Integridad de schemas | Verificar que los XSD requeridos existan y no apunten a ubicaciones remotas. | XSD local versionado | `tests/test_schema_versions.py` | implementado |
| Reenvío incierto de DE | Nunca reenviar un CDC sin resultado definitivo; ante falta de respuesta, consultar por CDC y reutilizar el payload exacto. | Guía DNIT de mejores prácticas para gestión del envío de DE (octubre 2024) | `kilasifen/infrastructure/jobs/document_attempts.py`, `kilasifen/infrastructure/jobs/workers.py`, `tests/application/test_emission_flow.py`, `tests/application/test_document_attempt_transactions.py` | implementado |
| Recibo Electrónico de Dinero | No presentar `iTiDE=8` como Recibo ni habilitar transmisión hasta contar con formato/validaciones oficiales completos. | Decreto 872/2023; Manual 150; `siRecepRDE_v150.xsd` publicado por DNIT | `docs/architecture/adr-0002-recibo-electronico.md` | pendiente de DNIT |

Nota 1: el unico binding `RDe` generado proviene de `FE_v141.xsd` (`kilasifen/engine/de/bindings/v150/fe_v141.py`) y conserva la estructura v141, sin `dSisFact`; los tests de muestras y de generacion lo usan. La emision de la plataforma no pasa por ese binding: `kilasifen/infrastructure/sifen/typed_xml_builder.py` arma el XML y lo valida contra `siRecepDE_v150.xsd` antes de firmar.

Nota 2: lo implementado es el envio individual de un `rEnviDe` armado con `_build_enviar_de_request_xml` (el mismo que usa `TransmisionDE.enviar_de_xml`); la plataforma lo guarda antes de enviarlo y lo transmite tal cual con `TransmisionDE._send_raw_xml`. `enviar_lote` y `enviar_lote_xml` arman el lote con el formato oficial (filas "Lote asincrono"), pero la plataforma todavia no envia por lote. `enviar_de(rde)` con firma envia una firma que no verifica; ese defecto se conservo a proposito y esta descrito en `docs/architecture/public-api.md` (seccion Problemas conocidos).

## Puntos NO DETERMINADO (lote y consultas)

Opcion elegida segun F00: la que no produce un documento falso ni un rechazo seguro, explicita y documentada.

| id | punto | que dice la fuente oficial | opcion elegida |
| --- | --- | --- | --- |
| L1 | Nombre del archivo dentro del ZIP del lote | MT §9.2 y Guia pp. 8-9 piden comprimir `rLoteDE`, sin nombre | `lote.xml` (`NOMBRE_ARCHIVO_LOTE`), una sola entrada, ZIP deflate con fecha fija para que el mismo lote de los mismos bytes |
| L2 | Namespace de `rLoteDE` | No hay XSD publicado de `rLoteDE` (el `ProtProcesLoteDE_v150.xsd` del MT Schema 5A no esta entre los XSD oficiales); el ejemplo de la Guia p. 8 no lo lleva | Sin namespace; cada `rDE` declara el suyo (MT §7.2.2.2) |
| L3 | `xsi:schemaLocation` en cada `rDE` del lote | Los ejemplos del MT §7.2.2.2 lo incluyen; ninguna regla lo exige | Se incluye (se agrega si falta), igual que en el envio sincronico |
| L4 | Tope de tamano del lote | MT §12.3.2.1 (p. 155): 10.000 KB del mensaje (0270); Guia p. 6 causa e de 0301: 1000 KB; la unidad KB no esta definida | 1.000.000 bytes del sobre SOAP completo, con el ZIP ya en base64 (la lectura mas restrictiva) |
| L5 | Blancos entre etiquetas dentro de un `rDE` ya firmado | MT §7.2.4 y Guia p. 4 los prohiben; quitarlos despues de firmar invalida la firma | Se rechaza el lote con `ValueError` (el firmador del engine ya firma sin blancos) |
| L6 | `0360` justo despues de un `0300` | MT Tabla F: "Numero del Lote inexistente"; no dice si puede ser transitorio | Error (`SifenLoteError`), sin reintentar (F66) |
| L7 | Codigo de consulta de lote fuera de 0360-0364, 0340 y 0320 | No documentado | Error (`SifenLoteError`), nunca pendiente |
| L8 | Consulta DTE: direccion, codigos, mensajes de pendiente, intervalo y plazos | Solo existen los XSD | Rutas conservadas como experimentales; sin tokens de pendiente por defecto; aviso en cada llamada |

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
