# Chunk 12

## Purpose

Complete `PASO 5` of the MVP: KuDE generation as both PDF (server-rendered)
and structured JSON data (for client-side rendering with custom branding).
Also wires the real SIFEN QR (with the actual signature DigestValue and
emitter CSC) into every signed XML.

## Why it exists

ERP integrators need either a ready-to-print PDF or the underlying
fields to render a branded representation. Both paths share one
extractor so values, labels and the QR URL are always identical.

The previous `dCarQR` was a placeholder with `DigestValue=0`. SIFEN
mandates the real DigestValue + a SHA-256 hash including the emitter
CSC; this chunk computes both and substitutes them after signing.

## Closed tasks

- `Task QR` commit `21e44f5` - SIFEN QR generator with byte-exact manual
  reproduction (Manual Tecnico v150 section 13.8.4).
- `Task QR-Wire` commit `9042eac` - post-sign substitution of dCarQR
  using the real DigestValue and emitter CSC. All 12 goldens regenerated.
- `Task PDF` commit `84d2999` - PDF renderer (fpdf2, A4 vertical) and
  shared data extractor.
- `Task API` commit `402c3cf` - GET /v1/emitters/{id}/documents/{id}/kude
  (PDF) and .../kude/data (JSON envelope).

## Main files

- `kilasifen/infrastructure/kude/qr_generator.py`
- `kilasifen/infrastructure/kude/xml_qr_injector.py`
- `kilasifen/infrastructure/kude/data_extractor.py`
- `kilasifen/infrastructure/kude/pdf_renderer.py`
- `kilasifen/infrastructure/sifen/engine.py`
- `kilasifen/application/documents/service.py`
- `kilasifen/api/routers/documents.py`
- `tests/infrastructure/test_kude_qr.py`
- `tests/infrastructure/test_kude_pdf.py`
- `tests/api/test_documents_kude_api.py`
- `tests/golden/*.xml` - regenerated with real DigestValue + cHashQR

## Decisions taken

- The `gCamFuFD/dCarQR` element sits outside the signed `<DE>` envelope,
  so we compute the QR after `sign_xml` and replace the element via
  string substitution. This preserves signxml's exact byte serialization
  (no XML re-emit, no namespace prefix changes, no XML declaration).
- The data extractor parses the signed XML directly. The XML is the
  source of truth; the typed contract is not consulted again at KuDE time.
- The CSC is consumed only inside `qr_generator.build_sifen_qr_url` (for
  the SHA-256 input) and never returned, logged, serialized or persisted.
- The JSON endpoint always emits keys (with `null`) so consumers can
  navigate the structure without defensive checks.
- All amounts are returned as strings to preserve decimal precision.

## Regenerating the goldens

The 12 goldens under `tests/golden/` embed the real DigestValue (which
depends on the cert + signed XML bytes) and the real `cHashQR` (which
depends on the emitter CSC). They are deterministic for the fixed test
fixture (`csc=ABCD0000000000000000000000000000`, `csc_id=0001`). The
certificate is now a self-signed PKCS#12 generated ephemerally by
`tests/conftest.py`; no certificate file or password is committed.

To regenerate after a deliberate change to the unsigned XML or the QR
URL parameters: drive the typed scenarios through the API as the
`tests/api/test_documents_typed_golden_api.py` flow does, then write
the resulting signed XML (with `apply_real_qr_to_signed_xml` applied)
to the matching `tests/golden/<scenario>.xml`. The tests will then
diff byte-exact.
