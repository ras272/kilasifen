# ADR-0004: Hash de las claves de consumidor

- Estado: aceptado
- Fecha: 2026-10-08
- Modifica: ADR-0001 (las claves se guardaban todas con PBKDF2-SHA256 salado)

## Contexto

Cada pedido autenticado verificaba la clave con PBKDF2-SHA256 de 210.000
iteraciones: unos 56 ms de CPU por pedido, y el doble con una clave de arranque,
que se verificaba dos veces. Medido el 2026-10-08 con `TestClient` y SQLite, un
`GET /v1/emitters/{id}` tardaba 61 ms, y el 83 % del tiempo era PBKDF2. Además
limitaba la API a unos 18 pedidos autenticados por segundo y por núcleo.

Un KDF lento protege secretos que se pueden adivinar, como las contraseñas. Una
clave de consumidor es `ks_` más `secrets.token_urlsafe(32)`, o sea 256 bits al
azar: nadie la deduce de su hash, sea rápido o lento.

## Decisión

- Las claves de consumidor se guardan como `sha256$<digest>` y se comparan en
  tiempo constante (`hmac.compare_digest`).
- Una clave guardada con PBKDF2 pasa a SHA-256 la primera vez que se usa, porque
  su valor sólo está disponible en ese momento. Una clave que nunca se usa queda
  con PBKDF2 y sigue siendo válida.
- Las claves de arranque (`KILA_SIFEN_API_KEYS`) las elige quien opera la
  instalación y su entropía es desconocida: siguen con PBKDF2 salado. La
  configuración es la fuente de verdad, así que su hash se comprueba una vez por
  proceso y por clave, no en cada pedido. Si la fila desaparece, se vuelve a
  guardar.

## Consecuencias

- Medido con el mismo banco: 3,9 ms por pedido con una clave de consumidor y
  4,2 ms con una de arranque, frente a 61 ms y 120 ms antes.
- Una filtración de la base no permite recuperar claves de consumidor (256 bits
  al azar) ni, con un costo razonable, claves de arranque débiles (PBKDF2).
