# ADR-0003: Alta de emisores desde el ERP (`emitters:create`)

- Estado: aceptado
- Fecha: 2026-10-07

## Contexto

ADR-0001 dejó el alta de emisores sólo en manos de `platform:admin`, porque el
RUC es una identidad global de la plataforma. Un ERP multiempresa da de alta a
cada cliente nuevo como un emisor, así que necesitaba una clave de
administrador o un paso manual por cliente. Además:

- si se perdía la respuesta del alta, el ERP no podía recuperar el
  `emitter_id`: repetir el alta respondía `409` y no existía un listado de
  emisores;
- el reintento de un job trabado (por ejemplo, porque se cayó el worker) sólo
  existía en la consola `/admin`.

## Decisión

- Nuevo scope de consumidor `emitters:create`. Con él, `POST /v1/emitters`
  crea emisores que quedan siempre a nombre del consumidor de la credencial;
  un `owner_consumer_id` de otro consumidor responde
  `403 emitters.owner_not_allowed`. `platform:admin` sigue pudiendo asignar
  cualquier consumidor.
- `GET /v1/emitters` con `tenant:read` lista los emisores del consumidor (con
  `platform:admin`, todos), con filtros `external_id` y `ruc`.
- `POST /v1/emitters/{emitter_id}/jobs/{job_id}/retry` con `fiscal:write` hace
  el mismo reintento que la consola, limitado a los jobs de un emisor del
  consumidor.
- Una credencial admite hasta cinco scopes, los cinco de consumidor.

RUC + DV y `external_id` siguen siendo únicos en toda la plataforma. Dos
emisores con el mismo RUC numerarían sus documentos por separado y chocarían
ante el SIFEN.

## Consecuencias

- Una credencial con `emitters:create` puede saber si un RUC ya está dado de
  alta (`409 emitters.tax_id_conflict`, aunque sea de otro consumidor) y puede
  ocupar un RUC antes que el ERP que de verdad lo atiende. No puede emitir por
  ese RUC, porque activar un certificado exige que sea del mismo RUC
  (`certificates.ruc_mismatch`), pero sí bloquear su alta: no hay endpoint
  para reasignar ni borrar emisores. Por eso el scope se otorga sólo a
  integradores de confianza.
- Como `external_id` es único global, cada ERP tiene que usar valores que no
  choquen con los de otros integradores; el portal recomienda un prefijo
  propio.
- El reintento del ERP no puede duplicar un documento. El outbox publica cada
  job una sola vez por su id y no lanza otra corrida mientras RQ tenga una en
  curso. Además, un intento sobre un DE que pudo llegar al SIFEN consulta el
  CDC antes de reenviar el mismo DE firmado (regla dura 6 de `CLAUDE.md`).
