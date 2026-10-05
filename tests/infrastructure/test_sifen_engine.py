from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from kilasifen.engine.sdk.errors import (
    SifenUnexpectedResponseError,
    SifenValidationError,
)
from kilasifen.infrastructure.sifen import engine as engine_module
from kilasifen.infrastructure.sifen.engine import (
    KilaSifenDocumentTransport,
    KilaSifenEmissionEngine,
    SubmissionOutcome,
    outcome_from_reception_body,
)
from kilasifen.infrastructure.sifen.typed_xml_builder import _resolve_emission_datetime

_NS = "http://ekuatia.set.gov.py/sifen/xsd"


def _reception_answer(protocol_children: str) -> bytes:
    """An ``rRetEnviDe`` as protProcesDE_v150.xsd lays it out."""

    return (
        f'<rRetEnviDe xmlns="{_NS}"><rProtDe>'
        "<Id>01800241355001001000000012026042711234567893</Id>"
        "<dFecProc>2026-10-01T10:15:00-03:00</dFecProc>"
        f"{protocol_children}"
        "</rProtDe></rRetEnviDe>"
    ).encode("utf-8")


def test_a_rejection_reports_its_first_error() -> None:
    outcome = outcome_from_reception_body(
        _reception_answer(
            "<dEstRes>Rechazado</dEstRes>"
            "<gResProc><dCodRes>1330</dCodRes>"
            "<dMsgRes>Es obligatorio informar el numero de casa del receptor"
            "</dMsgRes></gResProc>"
        )
    )

    assert outcome.result_code == "1330"
    assert outcome.result_message == (
        "Es obligatorio informar el numero de casa del receptor"
    )
    assert outcome.sifen_status == "rejected"


def test_an_observed_approval_is_approved_and_keeps_every_message() -> None:
    # DECISIONES F60; MT v150 cap. 12 p. 145: an AO is a valid DTE. The code
    # that comes with it is NO DETERMINADO, so it is never read as rejection.
    outcome = outcome_from_reception_body(
        _reception_answer(
            "<dEstRes>Aprobado con observación</dEstRes>"
            "<dProtAut>1234567890</dProtAut>"
            "<gResProc><dCodRes>1005</dCodRes>"
            "<dMsgRes>Transmision extemporanea del DE</dMsgRes></gResProc>"
            "<gResProc><dCodRes>0260</dCodRes>"
            "<dMsgRes>Autorizacion del DE satisfactoria</dMsgRes></gResProc>"
        )
    )

    assert outcome.sifen_status == "approved_with_observation"
    assert outcome.protocol == "1234567890"
    assert outcome.result_code == "1005"
    assert [message.code for message in outcome.messages] == ["1005", "0260"]
    assert outcome.processed_at == datetime(
        2026, 10, 1, 13, 15, tzinfo=timezone.utc
    )


def test_the_mt_layout_with_dEstRes_inside_gResProc_is_accepted() -> None:
    # MT v150 PP050/PP051 under PP05 (p. 46) and example §7.4 (p. 36).
    outcome = outcome_from_reception_body(
        _reception_answer(
            "<gResProc><dEstRes>Aprobado</dEstRes><dProtAut>4455667788</dProtAut>"
            "<dCodRes>0260</dCodRes><dMsgRes>Autorizacion satisfactoria</dMsgRes>"
            "</gResProc>"
        )
    )

    assert outcome.sifen_status == "approved"
    assert outcome.protocol == "4455667788"


def test_an_answer_without_dEstRes_is_only_approved_with_0260() -> None:
    approved = outcome_from_reception_body(
        _reception_answer(
            "<gResProc><dCodRes>0260</dCodRes><dMsgRes>ok</dMsgRes></gResProc>"
        )
    )
    unknown = outcome_from_reception_body(
        _reception_answer(
            "<gResProc><dCodRes>1330</dCodRes><dMsgRes>dato</dMsgRes></gResProc>"
        )
    )

    assert approved.sifen_status == "approved"
    assert unknown.sifen_status == "unknown"


def test_the_raw_answer_is_kept_as_received() -> None:
    body = _reception_answer("<dEstRes>Aprobado</dEstRes>")

    assert outcome_from_reception_body(body).response_raw == body.decode("utf-8")


@pytest.mark.parametrize(
    "body",
    [
        b"<html>proxy</html>",
        b"<rRetEnviDe><rProtDe>",
        b'<env:Fault xmlns:env="http://www.w3.org/2003/05/soap-envelope"/>',
    ],
)
def test_anything_but_an_answer_leaves_the_outcome_unknown(body: bytes) -> None:
    with pytest.raises(SifenUnexpectedResponseError):
        outcome_from_reception_body(body)


def test_resolve_emission_datetime_preserves_py_local_wall_time_from_offset() -> None:
    resolved = _resolve_emission_datetime(
        {"fecha_emision": "2026-04-26T23:21:14-03:00"}
    )

    assert resolved == "2026-04-26T23:21:14"


def test_resolve_emission_datetime_accepts_utc_z_suffix() -> None:
    resolved = _resolve_emission_datetime({"fecha_emision": "2026-04-27T02:21:14Z"})

    assert resolved == "2026-04-26T23:21:14"


def test_live_document_transport_disables_automatic_mutation_retries() -> None:
    transmision = MagicMock()
    transmision.__enter__.return_value = transmision
    transmision._send_raw_xml.return_value = _reception_answer(
        "<dEstRes>Aprobado</dEstRes>"
        "<gResProc><dCodRes>0260</dCodRes><dMsgRes>DE aprobado</dMsgRes></gResProc>"
    )

    with patch(
        "kilasifen.infrastructure.sifen.engine.TransmisionDE",
        return_value=transmision,
    ) as transmision_class:
        transport = KilaSifenDocumentTransport()

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


def test_a_resend_wraps_the_same_signed_rde_in_a_new_dId(monkeypatch) -> None:
    ids = iter([111, 222])
    monkeypatch.setattr(engine_module, "_generate_id", lambda: next(ids))
    engine, _ = _engine_with_payload()

    prepared = _prepare(engine)
    resend = engine.wrap_signed_document(signed_xml=prepared.signed_xml)

    assert "<dId>111</dId>" in prepared.request_xml
    assert "<dId>222</dId>" in resend
    assert f'Id="{_CDC}"' in resend
    assert prepared.request_xml.replace("<dId>111</dId>", "<dId>222</dId>") == resend


def test_dFecProc_without_offset_is_paraguay_time() -> None:
    outcome = outcome_from_reception_body(
        (
            f'<rRetEnviDe xmlns="{_NS}"><rProtDe>'
            "<dFecProc>2026-10-01T10:15:00</dFecProc>"
            "<dEstRes>Aprobado</dEstRes></rProtDe></rRetEnviDe>"
        ).encode("utf-8")
    )

    assert outcome.processed_at is not None
    assert outcome.processed_at.utcoffset() == timedelta(hours=-3)
