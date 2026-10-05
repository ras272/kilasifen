"""dFecFirma is the real signing time and is checked before signing (F21)."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest

from kilasifen.domain.common.paraguay_time import PARAGUAY_TZ
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.fiscal import build_qr_payload_from_signed_xml
from kilasifen.infrastructure.sifen import engine as engine_module
from kilasifen.infrastructure.sifen.engine import KilaSifenEmissionEngine
from kilasifen.infrastructure.sifen.typed_xml_builder import DCARQR_PENDING_SIGNATURE
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile
from tests._raw_xml import unsigned_rde

_CERT_PATH = Path(__file__).resolve().parents[1] / "test_cert.pfx"
_CERT_PASSWORD = "test1234"
_NS = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}
# Five hours after the 2026-04-25T10:00:00 emission of the payload.
_NOW = datetime(2026, 4, 25, 15, 30, 12, tzinfo=PARAGUAY_TZ)


@pytest.fixture
def cert_data() -> bytes:
    if not _CERT_PATH.exists():
        pytest.skip("test_cert.pfx not found")
    return _CERT_PATH.read_bytes()


def test_dfecfirma_is_the_signing_time_not_the_emission_date(cert_data) -> None:
    prepared = _prepare(_typed_document(), cert_data, now=_NOW)

    root = ET.fromstring(prepared.signed_xml.encode("utf-8"))
    assert root.find("s:DE/s:dFecFirma", _NS).text == "2026-04-25T15:30:12"
    assert root.find("s:DE/s:gDatGralOpe/s:dFeEmiDE", _NS).text == (
        "2026-04-25T10:00:00"
    )
    assert prepared.generated_xml.count("<dFecFirma>2026-04-25T15:30:12<") == 1


def test_signed_xml_replaces_the_pending_dcarqr_with_the_real_qr(cert_data) -> None:
    prepared = _prepare(_typed_document(), cert_data, now=_NOW)

    root = ET.fromstring(prepared.signed_xml.encode("utf-8"))
    dcarqr = root.find("s:gCamFuFD/s:dCarQR", _NS).text
    assert dcarqr == build_qr_payload_from_signed_xml(
        signed_xml=prepared.signed_xml,
        id_csc="0001",
        csc="ABCD0000000000000000000000000000",
        environment="test",
    )["url"]
    assert DCARQR_PENDING_SIGNATURE in prepared.generated_xml
    assert DCARQR_PENDING_SIGNATURE not in prepared.signed_xml
    assert DCARQR_PENDING_SIGNATURE not in prepared.request_xml


def test_future_emission_within_120_hours_is_signed_now(cert_data) -> None:
    # A future dFeEmiDE (allowed up to 120 h, 1151) no longer produces a
    # dFecFirma after the SIFEN clock (1004).
    prepared = _prepare(
        _typed_document(fecha="2026-04-28T09:00:00"), cert_data, now=_NOW
    )

    root = ET.fromstring(prepared.signed_xml.encode("utf-8"))
    assert root.find("s:DE/s:dFecFirma", _NS).text == "2026-04-25T15:30:12"


def test_certificate_expired_at_signing_time_is_refused(cert_data) -> None:
    # The ephemeral test certificate expires on 2035-01-01 (2450, NT 16).
    after_expiry = datetime(2035, 1, 2, 9, 0, 0, tzinfo=PARAGUAY_TZ)

    with pytest.raises(SifenValidationError, match="not_valid_at_signature"):
        _prepare(
            _typed_document(fecha="2035-01-02T08:00:00"), cert_data, now=after_expiry
        )


@pytest.mark.parametrize(
    ("fecha", "code"),
    [
        ("2026-03-20T10:00:00", "documents.fecha_emision.too_old"),
        ("2026-05-01T10:00:00", "documents.fecha_emision.too_far_ahead"),
    ],
)
def test_emission_outside_the_window_is_refused_before_signing(
    cert_data, fecha: str, code: str
) -> None:
    with pytest.raises(SifenValidationError, match=code):
        _prepare(_typed_document(fecha=fecha), cert_data, now=_NOW)


def test_raw_xml_with_a_signature_time_after_now_is_refused(cert_data) -> None:
    generated_xml, doc_id = unsigned_rde()
    future_signature = generated_xml.replace(
        "<dFecFirma>2026-04-25T10:05:00</dFecFirma>",
        "<dFecFirma>2026-04-25T16:00:00</dFecFirma>",
    )
    assert future_signature != generated_xml
    mapper = Mock()
    mapper.map_document.return_value = SimpleNamespace(
        generated_xml=future_signature, signed_xml=None, doc_id=doc_id
    )
    engine = KilaSifenEmissionEngine(
        mapper=mapper, transport=Mock(), clock=lambda: _NOW
    )

    with pytest.raises(SifenValidationError, match="fecha_firma.after_now"):
        engine.prepare_document(
            document=Mock(),
            emitter=SimpleNamespace(tax_environment="test", csc=None, csc_id=None),
            certificate_bytes=cert_data,
            certificate_password=_CERT_PASSWORD,
            stamping=Mock(),
        )


def test_extemporaneous_transmission_is_logged(cert_data, monkeypatch) -> None:
    # 130 h after the emission: approved with observation 1005 (§6.2.1).
    late = datetime(2026, 4, 30, 20, 0, 0, tzinfo=PARAGUAY_TZ)
    warning = Mock()
    monkeypatch.setattr(engine_module.logger, "warning", warning)

    _prepare(_typed_document(), cert_data, now=late)

    warning.assert_called_once()
    assert warning.call_args.args[0] == "documents.transmission.extemporaneous"
    assert warning.call_args.kwargs["extra"]["fiscal_warnings"] == [
        "documents.transmission.emission_far_from_now"
    ]


def _prepare(document: Document, cert_data: bytes, *, now: datetime):
    engine = KilaSifenEmissionEngine(transport=Mock(), clock=lambda: now)
    return engine.prepare_document(
        document=document,
        emitter=_emitter(),
        certificate_bytes=cert_data,
        certificate_password=_CERT_PASSWORD,
        stamping=_stamping(),
    )


def _typed_document(fecha: str = "2026-04-25T10:00:00") -> Document:
    now = datetime.now(timezone.utc)
    payload = {
        "numero": 7,
        "establecimiento": "001",
        "punto": "001",
        "fecha_emision": fecha,
        "cliente": {
            "naturaleza": 1,
            "tipo_operacion": 1,
            "tipo_contribuyente": 2,
            "ruc": "80025298-5",
            "razon_social": "CLIENTE FICTICIO SA",
        },
        "items": [
            {
                "descripcion": "Producto",
                "cantidad": "1",
                "precio_unitario": "110000",
                "afectacion": "gravado",
                "tasa": 10,
            }
        ],
    }
    return Document(
        id="doc-signing",
        emitter_id="emitter-1",
        external_id=None,
        idempotency_key=None,
        document_type="factura",
        payload_snapshot={
            "typed_contract": {"contract": "factura_v1", "payload": payload}
        },
        generated_xml=None,
        signed_xml=None,
        sifen_request_xml=None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=None,
        internal_status="queued",
        sifen_status=None,
        sifen_result_code=None,
        sifen_result_message=None,
        created_at=now,
        updated_at=now,
        security_code="364052981",
    )


def _emitter() -> Emitter:
    now = datetime.now(timezone.utc)
    return Emitter(
        id="emitter-1",
        external_id=None,
        ruc="44444401",
        dv="7",
        legal_name="EMISOR FICTICIO SA",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=now,
        updated_at=now,
        fiscal_profile=fictional_fiscal_profile(),
    )


def _stamping() -> Stamping:
    now = datetime.now(timezone.utc)
    return Stamping(
        id="stamp-1",
        emitter_id="emitter-1",
        number="12345678",
        start_date=date(2024, 3, 11),
        end_date=None,
        is_active=True,
        status="active",
        created_at=now,
        updated_at=now,
    )
