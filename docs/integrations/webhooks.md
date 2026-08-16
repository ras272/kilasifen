# Webhooks de KilaSifen v1

KilaSifen entrega un `POST` JSON por evento. Una entrega conserva el mismo
`X-Kila-Delivery-ID` y el mismo cuerpo exacto durante todos sus reintentos. Una
acción de replay solicitada por API crea una entrega nueva y, por lo tanto, un ID
nuevo.

## Firma y verificación

Cada request incluye:

| Header | Contenido |
| --- | --- |
| `X-Kila-Signature-Version` | `v1` |
| `X-Kila-Timestamp` | Unix time decimal en UTC |
| `X-Kila-Delivery-ID` | UUID durable de la entrega |
| `X-Kila-Event` | Tipo de evento, por ejemplo `document.approved` |
| `X-Kila-Signature` | `v1=` seguido del HMAC-SHA256 hexadecimal |

La entrada exacta del HMAC v1 es la concatenación binaria:

```text
v1 + "." + timestamp + "." + delivery_id + "." + event_type + "." + raw_body
```

`raw_body` son los bytes recibidos, antes de parsear o volver a serializar JSON.
El secreto del endpoint es la clave HMAC UTF-8. Los consumidores Python pueden
usar `kilasifen.infrastructure.webhooks.security.verify_signature`, que compara
en tiempo constante.

Las nuevas altas exigen un secreto de al menos 32 caracteres; se recomienda
generar 32 bytes aleatorios y codificarlos como base64url. La API nunca devuelve
ni muestra parcialmente el secreto y sólo informa `secret_configured: true`.

El consumidor debe aplicar este orden:

1. conservar los bytes crudos del body;
2. rechazar timestamps a más de 300 segundos del reloj local;
3. verificar el HMAC en tiempo constante;
4. consultar en almacenamiento durable si el delivery ID ya fue procesado;
5. ejecutar el cambio de negocio y guardar el delivery ID con una restricción
   `UNIQUE`, dentro de la misma transacción;
6. responder `2xx` solamente después del commit.

Un delivery ID repetido se considera éxito idempotente y no vuelve a ejecutar el
efecto de negocio. No se debe guardar el ID antes de verificar firma y frescura.
Los consumidores necesitan sincronización de reloj (NTP).

## Cuerpo

El JSON usa `snake_case` y este envelope estable:

```json
{
  "data": {"document_id": "..."},
  "delivery_id": "...",
  "occurred_at": "2026-08-16T20:00:00+00:00",
  "type": "document.approved"
}
```

## Reintentos y observabilidad

Son reintentables los errores de transporte y las respuestas `408`, `425`,
`429` y `5xx`. El backoff automático es 10 s, 30 s, 2 min, 5 min, 15 min,
30 min y 60 min. `max_attempts` acepta de 1 a 8 y su valor por defecto es 5.
Respuestas `2xx` terminan en `delivered`; otros `4xx` y redirecciones terminan en
`failed`. Al agotar intentos también termina en `failed` con
`max_attempts_exhausted` en el job. Mientras espera, delivery y job son
observables como `retry_pending` y `retry_scheduled`.

La API conserva como máximo 2 KiB de una respuesta para diagnóstico y redacta
campos comunes de credenciales. El transporte no descarga más de 64 KiB. Nunca
se debe depender del snapshot como copia completa de la respuesta.

## Política de red

Fuera de `development` sólo se acepta HTTPS. Al registrar y antes de cada intento
se resuelven y validan todas las direcciones del hostname. Se bloquean IPv4 e
IPv6 loopback, privadas, link-local, multicast, reservadas y no especificadas.
La conexión se fija a una IP ya validada mientras TLS continúa verificando el
hostname original; esto evita una segunda resolución susceptible a DNS
rebinding. KilaSifen no sigue redirecciones.

Estas validaciones de aplicación son defensa en profundidad. El despliegue debe
además aplicar egress firewall/proxy para impedir acceso del worker a redes
privadas, metadata cloud y servicios de control, permitiendo únicamente Internet
pública en los puertos requeridos.
