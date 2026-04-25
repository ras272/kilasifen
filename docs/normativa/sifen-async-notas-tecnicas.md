# SIFEN Async - Notas Tecnicas Operativas

## Fuente

- Documento base: `C:/Users/rassj/Desktop/Guía de Mejores Prácticas para la Gestión del Envío de DE.pdf`
- Enfoque: reglas de integracion asincrona por lote (`recibe-lote`, `consulta-lote`, `consulta` por CDC).

## Flujo de referencia

1. Enviar lote por `recibe-lote`.
2. Interpretar `dCodRes` del envio de lote.
3. Si el lote fue aceptado para procesamiento, consultar por `dProtConsLote` via `consulta-lote`.
4. Repetir consulta de lote hasta estado terminal.
5. Si la consulta de lote expira (`0364`), usar `consulta` por CDC.

## Endpoints a contemplar

- `https://{ambiente}/de/ws/async/recibe-lote.wsdl`
- `https://{ambiente}/de/ws/consultas/consulta-lote.wsdl`
- `https://{ambiente}/de/ws/consultas/consulta.wsdl`

## Reglas duras de lote

- Maximo `50 DE` por lote.
- Un solo `RUC emisor` por lote.
- Un solo tipo de DE por lote.
- Todos los DE deben ir firmados.
- El request del WS no debe superar `1000 KB`.

## Tabla de decisiones para Kila SIFEN

### 1) Respuesta de `recibe-lote` (`dCodRes`)

| Codigo | Interpretacion | Estado interno sugerido | Accion |
|---|---|---|---|
| `0300` | Lote recibido con exito | `lot_received` | Guardar `dProtConsLote`, crear job `sifen.lote.poll`, iniciar polling diferido |
| `0301` | Lote no encolado | `lot_not_queued` | No reenviar automaticamente; registrar causa y requerir correccion del lote |

### 2) Respuesta de `consulta-lote` (`dCodResLot`)

| Codigo | Interpretacion | Estado interno sugerido | Accion |
|---|---|---|---|
| `0360` | Numero de lote inexistente | `lot_not_found` | Marcar incidente operativo; intentar reconciliar por CDC antes de reenviar |
| `0361` | Lote en procesamiento | `lot_processing` | Mantener polling con intervalo minimo de 10 min |
| `0362` | Procesamiento concluido | `lot_done` | Parsear `gResProcLote` por CDC y cerrar estado de cada DE |
| `0364` | Consulta extemporanea | `lot_query_expired` | Cambiar estrategia a `consulta` por CDC de cada DE del lote |

### 3) Resultado por DE dentro de `0362` (`gResProcLote`)

| Campo | Ejemplo | Estado interno sugerido | Accion |
|---|---|---|---|
| `dEstRes` | `Aprobado` | `approved` | Cerrar DE en estado terminal aprobado |
| `dEstRes` | `Aprobado con Observacion` | `approved_with_observation` | Cerrar DE aprobado con alerta funcional |
| `dEstRes` | `Rechazado` | `rejected` | Cerrar DE rechazado; conservar `dCodRes` y `dMsgRes` para remediacion |

### 4) Respuesta de `consulta` por CDC (`dCodRes`)

| Codigo | Interpretacion | Estado interno sugerido | Accion |
|---|---|---|---|
| `0420` | No existe o no aprobado | `not_found_or_not_approved` | Verificar primero estado de lote y evitar reenvio prematuro |
| `0422` | CDC encontrado y aprobado | `approved` | Persistir `xContenDE`, cerrar DE aprobado |

## Politica de polling recomendada

- Primer polling de lote: `+10 minutos` desde `0300`.
- Polling subsecuente: intervalos `>= 10 minutos`.
- Ventana operativa de procesamiento en alta carga: hasta `24 horas`.
- Si el lote supera `48 horas` para consulta de lote, migrar a consulta por CDC (`0364`).

## Politica anti-duplicados (obligatoria)

- No reenviar un CDC sin estado terminal de SIFEN (`Aprobado`, `Aprobado con Observacion` o `Rechazado`).
- Antes de cualquier reenvio, consultar lote/CDC para confirmar que no sigue en procesamiento.
- Bloqueos por RUC pueden ocurrir por:
  - lote vacio o invalido
  - CDC repetido en el mismo lote
  - CDC repetido en lotes distintos aun en procesamiento
  - lote repetido varias veces

## Checklist de implementacion en Kila SIFEN

1. Guardar siempre request/response crudos de `recibe-lote`, `consulta-lote`, `consulta`.
2. Persistir tabla de mapeo `codigo_sifen -> estado_interno -> accion`.
3. Mantener idempotencia por `CDC` y por `external_id` de ERP.
4. Implementar scheduler con backoff controlado para polling de lote.
5. Separar errores `transport`, `fiscal_validation`, `sifen_rejection`, `lot_not_queued`.
6. Exponer webhooks por transicion de estado (ej: `de.approved`, `de.rejected`, `de.processing_timeout`).

## Nota de diseno

- En caso de corte de comunicacion al enviar lote (sin `dProtConsLote` en respuesta), recuperar estado usando CDC de DE enviados en ese intento.
- Esta recuperacion debe ejecutarse antes de cualquier reenvio para evitar duplicados y bloqueos por RUC.
