from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from kilasifen.engine.de.bindings.v150.ws_si_recep_de_v150 import RRetEnviDe
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen import engine as engine_module
from kilasifen.infrastructure.sifen.engine import (
    KilaSifenDocumentTransport,
    KilaSifenEmissionEngine,
    SubmissionOutcome,
    _normalize_response,
)
from kilasifen.infrastructure.sifen.typed_xml_builder import _resolve_emission_datetime


class _FakeResult:
    def __init__(self, code=None, message=None):
        self.dCodRes = code
        self.dMsgRes = message


class _FakeProt:
    def __init__(self, *, status=None, result=None):
        self.dEstRes = status
        self.gResProc = result


class _FakeResponse:
    def __init__(self, prot):
        self.rProtDe = prot


def test_normalize_response_reads_protocol_result_nodes() -> None:
    response = _FakeResponse(
        _FakeProt(
            status="Rechazado",
            result=_FakeResult(
                code="1330",
                message="Es obligatorio informar el numero de casa del receptor",
            ),
        )
    )

    result_code, result_message, status = _normalize_response(response)

    assert result_code == "1330"
    assert result_message == "Es obligatorio informar el numero de casa del receptor"
    assert status == "rejected"


def test_resolve_emission_datetime_preserves_py_local_wall_time_from_offset() -> None:
    resolved = _resolve_emission_datetime(
        {"fecha_emision": "2026-04-26T23:21:14-03:00"}
    )

    assert resolved == "2026-04-26T23:21:14"


def test_resolve_emission_datetime_accepts_utc_z_suffix() -> None:
    resolved = _resolve_emission_datetime({"fecha_emision": "2026-04-27T02:21:14Z"})

    assert resolved == "2026-04-26T23:21:14"


def test_live_document_transport_disables_automatic_mutation_retries() -> None:
    response = _FakeResponse(
        _FakeProt(
            status="Aprobado",
            result=_FakeResult(code="0260", message="DE aprobado"),
        )
    )
    transmision = MagicMock()
    transmision.__enter__.return_value = transmision
    transmision._send_raw_xml.return_value = b"<rRetEnviDe/>"
    transmision._como_respuesta.return_value = response

    with patch(
        "kilasifen.infrastructure.sifen.engine.TransmisionDE",
        return_value=transmision,
    ) as transmision_class:
        transport = KilaSifenDocumentTransport()
        transport.serializer = MagicMock()
        transport.serializer.render.return_value = "<response />"

        outcome = transport.submit(
            request_xml="<rEnviDe><dId>42</dId></rEnviDe>",
            tax_environment="test",
            certificate_bytes=b"certificate",
            certificate_password="password",
        )

    transmision_class.assert_called_once_with(
        ambiente=2,
        pkcs12_data=b"certificate",
        pkcs12_password="password",
        max_retries=0,
    )
    transmision._send_raw_xml.assert_called_once_with(
        "recep_de", "<rEnviDe><dId>42</dId></rEnviDe>"
    )
    transmision._como_respuesta.assert_called_once_with(b"<rRetEnviDe/>", RRetEnviDe)
    assert outcome.sifen_status == "approved"


_CDC = "01800241355001001000000012026042711234567893"
_SIGNED_XML = (
    '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
    f'<DE Id="{_CDC}"/>'
    "<Signature/></rDE>"
)


def _engine_with_payload(*, signed_xml=_SIGNED_XML, doc_id=_CDC):
    mapper = Mock()
    mapper.map_document.return_value = SimpleNamespace(
        generated_xml=signed_xml,
        signed_xml=signed_xml,
        doc_id=doc_id,
    )
    transport = Mock()
    return KilaSifenEmissionEngine(mapper=mapper, transport=transport), transport


def _prepare(engine, *, tax_environment="test"):
    return engine.prepare_document(
        document=Mock(),
        emitter=SimpleNamespace(tax_environment=tax_environment),
        certificate_bytes=b"certificate",
        certificate_password="password",
        stamping=Mock(),
    )


def test_prepared_request_carries_the_dId_that_will_travel(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "_generate_id", lambda: 260427112345)
    engine, _ = _engine_with_payload()

    prepared = _prepare(engine)

    assert "<dId>260427112345</dId>" in prepared.request_xml
    assert "<dId>1</dId>" not in prepared.request_xml
    assert f'Id="{_CDC}"' in prepared.request_xml
    assert prepared.cdc == _CDC
    assert prepared.signed_xml == _SIGNED_XML


def test_prepare_never_contacts_sifen() -> None:
    engine, transport = _engine_with_payload()

    _prepare(engine)

    transport.submit.assert_not_called()


def test_prepare_refuses_a_document_without_cdc() -> None:
    engine, _ = _engine_with_payload(doc_id=None)

    with pytest.raises(SifenValidationError, match="doc_id"):
        _prepare(engine)


def test_prepare_refuses_an_emitter_from_another_environment() -> None:
    engine, _ = _engine_with_payload()

    with pytest.raises(SifenValidationError, match="tax environment"):
        _prepare(engine, tax_environment="production")


def test_submit_prepared_sends_the_persisted_request_unchanged() -> None:
    engine, transport = _engine_with_payload()
    answer = SubmissionOutcome(
        response_raw="<rRetEnviDe/>",
        sifen_status="approved",
        result_code="0260",
        result_message="Aprobado",
    )
    transport.submit.return_value = answer

    outcome = engine.submit_prepared(
        request_xml="<rEnviDe><dId>7</dId></rEnviDe>",
        emitter=SimpleNamespace(tax_environment="test"),
        certificate_bytes=b"certificate",
        certificate_password="password",
    )

    assert outcome is answer
    transport.submit.assert_called_once_with(
        request_xml="<rEnviDe><dId>7</dId></rEnviDe>",
        tax_environment="test",
        certificate_bytes=b"certificate",
        certificate_password="password",
    )
