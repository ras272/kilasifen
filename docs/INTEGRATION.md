# Integration guide — Kila SIFEN para ERPs

Cómo integrar tu ERP (multi-tenant SaaS o single-tenant) con Kila SIFEN para emitir documentos electrónicos paraguayos.

## Modelo mental en una frase

Tu ERP maneja **negocio** (clientes, productos, cobros, UI). Kila SIFEN maneja **lo fiscal** (firmar XMLs, hablar SOAP con SET, generar KuDE, eventos). La frontera entre los dos es el momento que se firma el XML.

---

## Glosario rápido

| Término | Significado |
|---|---|
| **DE** | Documento Electrónico — factura/NC/etc. en formato XML antes de aprobación SIFEN |
| **DTE** | DE aprobado por SIFEN (transición DE → DTE cuando SIFEN responde `0260`) |
| **CDC** | Código de Control, 44 caracteres, identificador único del DE en SIFEN |
| **CSC** | Código de Seguridad del Cliente, 32 caracteres, lo da SIFEN al darse de alta. Se usa para hashear el QR. NUNCA se comparte. |
| **Timbrado** | Permiso fiscal con número y vigencia, emitido por SET. Cada DE se emite "bajo" un timbrado. |
| **Establecimiento + Punto** | Sucursales lógicas dentro de un emisor (3+3 dígitos cada uno) |
| **KuDE** | Representación gráfica del DE (PDF/HTML) con QR para verificación pública |
| **Eventos** | Acciones post-emisión: cancelación, inutilización, etc. |
| **Emisor** | Tenant fiscal en Kila: 1 RUC + 1 cert + N timbrados + N CSCs |

---

## Quién guarda qué

| Dato | Tu ERP | Kila SIFEN |
|---|---|---|
| Cuenta de tenant (email, password, plan) | ✅ | — |
| Catálogo de productos y clientes del tenant | ✅ | — |
| RUC + datos fiscales del tenant | ✅ + ✅ | ✅ (en `EmitterModel`) |
| Cert P12 | ❌ (form upload) | ✅ (encrypted at-rest) |
| CSC | ❌ (form upload) | ✅ (encrypted at-rest) |
| Timbrado vigencias | ✅ (cache) | ✅ (fuente de verdad fiscal) |
| Borradores de factura | ✅ | — |
| Factura emitida | ✅ (referencia: `kila_doc_id`, `cdc`, status) | ✅ (XML firmado, PDF, JSON, eventos) |
| Lógica de cobro/pago | ✅ | — |
| Email al cliente final | ✅ (con Resend / SendGrid / SES) | — |
| Conservación legal del XML 5 años | Decisión tuya | Kila lo conserva en DB |
| Auditoría fiscal/contable | ✅ | — |

---

## Auth

Header obligatorio en cada request:

```
X-API-Key: <tu_api_key>
```

Por ahora hay un set único de API keys configurado vía `KILA_SIFEN_API_KEYS` (env var). Si querés trazabilidad por cliente, podés generar una API key distinta por tenant del ERP, o seguir con una sola y diferenciar por logs (con `correlation_id`).

---

## Momento 1 — Onboarding del tenant en tu ERP

Cada tenant nuevo en tu ERP es una empresa paraguaya distinta que va a emitir bajo su propio RUC.

### Fase 1.A — Registro general (no fiscal todavía)

```
Cliente ────────────────▶ Tu ERP
        sign up estándar
        (email, password, nombre empresa)

Tu ERP guarda en SU DB:
  tenants(id, email, plan, fiscal_status="pending", ...)
  
Estado: puede entrar al ERP, configurar productos y clientes,
pero NO puede emitir facturas.
```

En esta fase, **Kila SIFEN no se entera de nada**. 100% lógica de tu ERP.

### Fase 1.B — Onboarding fiscal (cuando el tenant quiere emitir)

Pantalla de "Configuración Fiscal" en tu ERP. Wizard con tabs (estilo FacturaSend):

```
[ Datos Fiscales ] [ Logo ] [ Ambiente ] [ Certificado ] [ API Key ] [ Off-line ]
```

Cada tab pide:

**Datos Fiscales**
- RUC (8 dígitos) + DV (1 dígito)
- Razón social oficial (debe coincidir con el RUC)
- Nombre fantasía (opcional)
- Dirección, departamento, distrito, ciudad
- Código actividad económica (con desplegable)
- Email de contacto fiscal

**Ambiente**
- Toggle "Conectado con SIFEN"
- Toggle "Ambiente SIFEN en Producción" (con warning de irreversible)
- Versión Manual Técnico SET (default 150)
- **Id del Código de Seguridad del Cliente (SET)** (default `0001`)
- **Código de Seguridad del Cliente** (32 chars alfanuméricos)

**Certificado**
- Drag & drop del archivo `.p12` o `.pfx`
- Password del certificado

**Timbrado activo**
- Número de timbrado (8 dígitos)
- Fecha inicio vigencia
- Fecha fin vigencia
- Establecimiento (default `001`)
- Punto de expedición (default `001`)

> **Naming**: usá los nombres en español que la SET y FacturaSend ya impusieron en la cabeza del usuario paraguayo. Evitá acrónimos como "CSC" en tu UI — escribilos completos como "Código de Seguridad del Cliente".

### Fase 1.C — Tu ERP backend hace esto contra Kila

```python
# 1. Crear el emisor en Kila
response = kila_api.post("/v1/emitters", json={
    "external_id": f"tenant-{tenant.id}",     # tu mapeo interno
    "ruc": form.ruc,
    "dv": form.dv,
    "legal_name": form.razon_social,
    "tax_environment": form.ambiente,         # "test" | "produccion"
    "csc": form.csc,
    "csc_id": form.id_csc,
})
kila_emitter_id = response["data"]["emitter"]["id"]

# 2. Subir el cert
cert_response = kila_api.post(
    f"/v1/emitters/{kila_emitter_id}/certificates",
    files={"file": form.p12_file},
    data={"password": form.p12_password},
)
cert_id = cert_response["data"]["certificate"]["id"]
kila_api.post(f"/v1/emitters/{kila_emitter_id}/certificates/{cert_id}/activate")

# 3. Cargar timbrado
stamping_response = kila_api.post(
    f"/v1/emitters/{kila_emitter_id}/stampings",
    json={
        "number": form.timbrado_numero,
        "start_date": form.start,
        "end_date": form.end,
    },
)
stamping_id = stamping_response["data"]["stamping"]["id"]
kila_api.post(f"/v1/emitters/{kila_emitter_id}/stampings/{stamping_id}/activate")

# 4. Registrar webhook para recibir notificaciones
webhook_secret = generate_random_secret()
kila_api.post(f"/v1/emitters/{kila_emitter_id}/webhooks", json={
    "url": f"https://api.tuerp.com/webhooks/sifen/{tenant.id}",
    "secret": webhook_secret,
    "event_subscriptions": [
        "document.approved",
        "document.rejected",
        "document.cancelled",
        "numbering.inutilized",
    ],
    "retry_policy": {"max_attempts": 5},
})

# 5. Verificar salud antes de marcar al tenant como "listo"
health = kila_api.get(f"/v1/emitters/{kila_emitter_id}/health")["data"]
assert health["has_active_certificate"]
assert health["has_active_stamping"]
assert health["queue_failed_count"] == 0

# 6. Guardar el mapeo en TU DB
tenants.update(tenant.id, {
    "kila_emitter_id": kila_emitter_id,
    "fiscal_status": "ready_test" if form.ambiente == "test" else "ready_production",
    "webhook_secret": webhook_secret,
})
```

**Estado del tenant ahora**: `ready_test` → puede emitir contra SIFEN test sin riesgo fiscal.

### Fase 1.D — Validación con SIFEN test (recomendado)

Antes de habilitar producción, hacé que el tenant emita 1–2 facturas de prueba contra SIFEN test desde tu UI normal con datos reales. Si funcionan, le mostrás un botón "Pasar a producción" que pide cert + CSC + timbrado de **producción** (son distintos de los de test).

---

## Momento 2 — Operación diaria

Una vez que el tenant está `ready_production`, cada vez que emite una factura:

### Flujo de emisión

```
Usuario en el ERP:
  - Selecciona cliente, items, condición de pago
  - Da "Confirmar factura"
                    │
                    ▼
Tu ERP backend:
  - Valida campos en su lógica de negocio
  - Llama a Kila:

    POST /v1/emitters/{kila_emitter_id}/documents/facturas
    {
      "external_id": f"fac-{tenant.id}-{factura_id_interno}",
      "idempotency_key": f"fac-{factura_id_interno}",
      "payload": {
        "establecimiento": "001",
        "punto": "001",
        # numero NO se manda — Kila lo asigna server-side
        "fecha_emision": "2026-04-26T10:30:00",
        "moneda": "PYG",
        "tipo_transaccion": "venta_mercaderia",
        "indicador_presencia": "presencial",
        "cliente": { ... datos del cliente desde tu DB ... },
        "condicion_operacion": { ... },
        "items": [ ... ]
      }
    }
                    │
                    ▼
Kila responde 202 Accepted en ~50 ms:
{
  "data": {
    "document": { "id": "doc-uuid", "internal_status": "queued" },
    "job": { "id": "job-uuid", "status": "queued" }
  }
}
                    │
                    ▼
Tu ERP backend:
  - Guarda en SU DB:
    invoices.update(factura.id, {
      kila_document_id: "doc-uuid",
      status: "submitted",
      submitted_at: now()
    })
  - Muestra al usuario: "✓ Enviada a SIFEN, esperando aprobación..."
```

### Mientras tanto, en background

```
Kila worker:
  - Reserva número fiscal atómico (ej: 0000123)
  - Construye XML del rDE
  - Calcula CDC (módulo 11)
  - Firma con cert PKCS12 (signxml)
  - Inyecta dCarQR (URL del QR oficial)
  - POST SOAP a sifen-test/prod (1–3 segundos típicamente)
  - Persiste estado final
  - Dispara webhook hacia tu ERP
                    │
                    ▼
Tu ERP recibe webhook:
  POST https://api.tuerp.com/webhooks/sifen/{tenant_id}
  Headers:
    X-Signature: hmac_sha256_del_body_con_el_secret
    X-Event-Type: document.approved
  Body:
  {
    "event_id": "...",
    "document_id": "doc-uuid",
    "cdc": "01800241355001001000000722026042611234567895",
    "sifen_status": "approved",
    "sifen_protocol": "...",
    "sifen_result_code": "0260",
    "sifen_result_message": "Autorización del DE satisfactoria",
    "established_at": "2026-04-26T10:30:15-03:00"
  }
                    │
                    ▼
Tu ERP webhook handler:
  - Verifica HMAC con el secret del tenant
  - Identifica al tenant por la URL (/webhooks/sifen/{tenant_id})
  - Update en SU DB
  - Notifica al usuario por email/notification
```

### Verificación HMAC del webhook (ejemplo Python)

```python
import hmac
import hashlib

def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.post("/webhooks/sifen/{tenant_id}")
async def receive_webhook(tenant_id: str, request: Request):
    body = await request.body()
    signature = request.headers.get("X-Signature", "")
    
    tenant = tenants.find(tenant_id)
    if not verify_signature(body, signature, tenant.webhook_secret):
        return Response(status_code=401)
    
    event = json.loads(body)
    event_type = request.headers.get("X-Event-Type")
    
    if event_type == "document.approved":
        on_document_approved(tenant, event)
    elif event_type == "document.rejected":
        on_document_rejected(tenant, event)
    elif event_type == "document.cancelled":
        on_document_cancelled(tenant, event)
    
    return Response(status_code=204)
```

### Mostrar el documento al usuario / al cliente final

```python
# Para mostrar en pantalla los datos (renderizar con tu propio branding):
data = kila_api.get(
    f"/v1/emitters/{tenant.kila_emitter_id}/documents/{kila_doc_id}/kude/data"
)
# → JSON con: tipo_label, cdc.groups, emisor, receptor, items[],
#             totales, qr.url, consulta_publica.portal_url

# Para descargar PDF estándar (entregar al cliente final):
pdf = kila_api.get(
    f"/v1/emitters/{tenant.kila_emitter_id}/documents/{kila_doc_id}/kude"
)
# → bytes PDF, mandalo por email con Resend o servelo()

# Para descargar XML legal (conservar 5 años):
xml = kila_api.get(
    f"/v1/emitters/{tenant.kila_emitter_id}/documents/{kila_doc_id}/xml"
)
# → XML firmado oficial
```

### Envío al cliente final

Esto lo hace **tu ERP**, no Kila. Flujo típico:

```python
def on_document_approved(tenant, webhook_data):
    invoice = invoices.find_by_kila_id(webhook_data["document_id"])
    
    pdf = kila_api.get_bytes(
        f"/v1/emitters/{tenant.kila_emitter_id}/documents/{webhook_data['document_id']}/kude"
    )
    xml = kila_api.get_text(
        f"/v1/emitters/{tenant.kila_emitter_id}/documents/{webhook_data['document_id']}/xml"
    )
    
    resend.emails.send(
        from_=tenant.fiscal_email,
        to=invoice.client_email,
        subject=f"Factura electrónica N° {invoice.numero}",
        html=render_template("factura_email.html", invoice=invoice),
        attachments=[
            {"filename": f"factura-{invoice.numero}.pdf", "content": pdf},
            {"filename": f"factura-{invoice.numero}.xml", "content": xml},
        ],
    )
```

---

## Momento 3 — Casos especiales / errores

### Si SIFEN rechaza

Webhook llega con `document.rejected`:

```json
{
  "document_id": "...",
  "sifen_status": "rejected",
  "sifen_result_code": "1330",
  "sifen_result_message": "Es obligatorio informar el número de casa del receptor"
}
```

Tu ERP debe:
1. Marcar factura como `rejected` en tu DB
2. Mostrar al usuario el mensaje SIFEN traducido a humano:
   `"Es obligatorio informar el número de casa del receptor (1330)"` →
   `"Falta el número de casa del cliente. Editá el cliente y agregalo."`
3. Permitir corrección y re-emisión (con NUEVO `idempotency_key`)
4. **El número de la factura rechazada queda quemado** (consumido en SIFEN). Hay que **inutilizar el rango** para limpiar la secuencia (POST `/inutilizations`).

### Si el usuario quiere cancelar

Dentro de plazo (48 h FE, 168 h NC):

```python
kila_api.post(
    f"/v1/emitters/{tenant.kila_emitter_id}/documents/{kila_doc_id}/cancel",
    json={"motivo": "Devolución del producto"}  # 5–500 chars
)
# 202 Accepted con event_id
# webhook document.cancelled cuando SIFEN apruebe
```

Fuera de plazo: tu ERP debe forzar emisión de **Nota de Crédito** que compense.

### Cert por vencer

Background job en tu ERP que diariamente consulta `/v1/emitters/{id}/health` para todos los tenants y avisa cuando:

- `certificate_valid_until` < 30 días → "Renová tu certificado SIFEN antes de X fecha"
- `stamping_valid_until` < 30 días → "Tu timbrado vence pronto, gestioná uno nuevo"
- `queue_failed_count > 0` → "Hay N facturas fallidas, revisá"

### Tenant suspende el servicio

```python
kila_api.post(f"/v1/emitters/{tenant.kila_emitter_id}/deactivate")
```

El emisor queda inactivo en Kila — no acepta más emisiones, pero los datos históricos se preservan (compliance fiscal: 5 años).

---

## Endpoints disponibles (resumen)

Todos requieren `X-API-Key`. Todos los recursos están **scoped por `emitter_id`** en el path.

### Emisores
```
POST   /v1/emitters
GET    /v1/emitters/{id}
PATCH  /v1/emitters/{id}
POST   /v1/emitters/{id}/deactivate
GET    /v1/emitters/{id}/health
```

### Certificados
```
POST   /v1/emitters/{id}/certificates
GET    /v1/emitters/{id}/certificates
POST   /v1/emitters/{id}/certificates/{cid}/activate
```

### Timbrados
```
POST   /v1/emitters/{id}/stampings
GET    /v1/emitters/{id}/stampings
POST   /v1/emitters/{id}/stampings/{sid}/activate
```

### Documentos
```
POST   /v1/emitters/{id}/documents              # genérico (XML crudo)
POST   /v1/emitters/{id}/documents/facturas     # tipado (recomendado)
POST   /v1/emitters/{id}/documents/notas-credito
GET    /v1/emitters/{id}/documents              # listar con filtros
GET    /v1/emitters/{id}/documents/{did}        # obtener + job asociado
GET    /v1/emitters/{id}/documents/{did}/xml    # XML firmado
GET    /v1/emitters/{id}/documents/{did}/kude   # PDF
GET    /v1/emitters/{id}/documents/{did}/kude/data  # JSON
```

### Eventos
```
POST   /v1/emitters/{id}/documents/{did}/cancel
POST   /v1/emitters/{id}/inutilizations
GET    /v1/emitters/{id}/events/{eid}
```

### Jobs (cola async)
```
GET    /v1/emitters/{id}/jobs/{jid}
GET    /v1/jobs                                 # listar (admin)
```

### Webhooks
```
POST   /v1/emitters/{id}/webhooks
GET    /v1/emitters/{id}/webhooks
POST   /v1/emitters/{id}/webhooks/{wid}/deliveries/replay
GET    /v1/emitters/{id}/webhook-deliveries/{deliveryid}
GET    /v1/webhook-deliveries                   # listar (admin)
```

### Consultas SIFEN
```
GET    /v1/queries/ruc/{ruc}                    # consultar RUC en SET
GET    /v1/queries/documents/{cdc}              # consultar estado en SIFEN
```

### Health/ready
```
GET    /health
GET    /ready
```

---

## UX hints concretos para tu ERP

1. **Estado de la factura siempre visible**: badge en lista con `pending` / `submitted` / `approved` / `rejected` / `cancelled`.
2. **No bloquees la UI esperando aprobación**: cargás 202, mostrás "Procesando..." y actualizás cuando llega el webhook (Server-Sent Events o polling cortés cada 3 s con back-off).
3. **Mensajes SIFEN traducidos a humanos**: mantené un mapping de `dCodRes` → texto amigable.
4. **Antes de habilitar producción**: pantalla de "Diagnóstico SIFEN" que llama `/health` y muestra ✓/✗ por componente.
5. **Botón "Reintentar"** en facturas rejected — abre el formulario pre-cargado con los datos y permite corregir.
6. **Histórico de eventos** por documento: timeline (creada → enviada → aprobada → cancelada).
7. **Counters operativos** en el dashboard: facturas pendientes, fallidas, cert por vencer, timbrado por vencer.

---

## Resumen en una línea

Tu ERP es la cara visible al cliente final. Kila SIFEN es el motor fiscal invisible que tu ERP llama cuando hay que tocar la SET. Vos enriqueces lo que la SET pide con UX, branding, lógica de negocio y onboarding. Kila garantiza que lo que sale a SIFEN es válido, firmado y aprobado.
