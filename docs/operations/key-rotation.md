# Rotación de secretos

## API key de consumidor

1. Emitir otra clave con los mismos scopes mediante
   `POST /v1/admin/consumers/{consumer_id}/credentials`.
2. Guardar `api_key` una sola vez en el backend consumidor.
3. Cambiar el consumidor y verificar tráfico.
4. Revocar la anterior con
   `POST /v1/admin/consumers/{consumer_id}/credentials/{credential_id}/revoke`.

KilaSifen conserva sólo PBKDF2-SHA256 salado y el prefijo no secreto.

## CSC y certificado

Cargar el reemplazo con `secrets:write`, validar RUC/vigencia, probar en SIFEN test
y activar. La API nunca devuelve CSC, password ni PKCS#12.

## Clave maestra Fernet

No existe dual-read automático. Programar mantenimiento:

1. detener API/worker y respaldar PostgreSQL;
2. offline, descifrar cada CSC/PFX/password con la clave anterior y re-cifrar
   inmediatamente con la nueva, sin plaintext en disco;
3. actualizar registros en una transacción;
4. cambiar `KILA_SIFEN_ENCRYPTION_KEY` en API, worker y migraciones;
5. arrancar, verificar lecturas/readiness y eliminar la clave anterior después.

Ensayar el procedimiento sobre una copia de staging.
