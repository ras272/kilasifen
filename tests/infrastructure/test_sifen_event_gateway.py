from types import SimpleNamespace

import pytest

from kilasifen.engine.sdk.errors import (
    SifenUnexpectedResponseError,
    SifenValidationError,
)
from kilasifen.infrastructure.sifen import event as event_module
from kilasifen.infrastructure.sifen.event import (
    KilaSifenEventGateway,
    _build_enviar_evento_request_xml,
    _normalize_response,
)


def test_normalize_response_accepts_event_shape_payload() -> None:
    response_raw = """
<rRetEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <dFecProc>2026-04-27T00:00:00-03:00</dFecProc>
  <gResProcEVe>
    <dEstRes>Aprobado</dEstRes>
    <dProtAut>123456789</dProtAut>
    <gResProc>
      <dCodRes>0600</dCodRes>
      <dMsgRes>Evento registrado correctamente</dMsgRes>
    </gResProc>
  </gResProcEVe>
</rRetEnviEventoDe>
""".strip()

    result_code, result_message, status, protocol = _normalize_response(response_raw)

    assert result_code == "0600"
    assert result_message == "Evento registrado correctamente"
    assert status == "approved"
    assert protocol == "123456789"


@pytest.mark.parametrize("foreign_code", ["0260", "0300"])
def test_only_0600_registers_an_event(foreign_code: str) -> None:
    # MT v150 §12.3.6.3 BU01 (p. 158); 0260 (§12.3.1.3) and 0300 (§12.3.2.3)
    # belong to other services (DECISIONES F70).
    response_raw = (
        '<rRetEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
        "<gResProcEVe><dEstRes>Aprobado</dEstRes>"
        f"<gResProc><dCodRes>{foreign_code}</dCodRes><dMsgRes>x</dMsgRes>"
        "</gResProc></gResProcEVe></rRetEnviEventoDe>"
    )

    _code, _message, status, _protocol = _normalize_response(response_raw)

    assert status == "rejected"


def test_an_event_answer_without_code_stays_pending() -> None:
    response_raw = (
        '<rRetEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
        "<gResProcEVe><dEstRes>Aprobado</dEstRes></gResProcEVe>"
        "</rRetEnviEventoDe>"
    )

    _code, _message, status, _protocol = _normalize_response(response_raw)

    assert status == "submitted"


def test_normalize_response_treats_0600_as_approved() -> None:
    response_raw = """
<rRetEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <dFecProc>2026-04-27T00:00:00-03:00</dFecProc>
  <gResProcEVe>
    <gResProc>
      <dCodRes>0600</dCodRes>
      <dMsgRes>Evento registrado correctamente</dMsgRes>
    </gResProc>
  </gResProcEVe>
</rRetEnviEventoDe>
""".strip()

    result_code, result_message, status, protocol = _normalize_response(response_raw)

    assert result_code == "0600"
    assert result_message == "Evento registrado correctamente"
    assert status == "approved"
    assert protocol is None


def test_normalize_response_accepts_de_style_payload() -> None:
    response_raw = """
<rRetEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <rProtDe>
    <dEstRes>Rechazado</dEstRes>
    <gResProc>
      <dCodRes>1299</dCodRes>
      <dMsgRes>Error de validación</dMsgRes>
    </gResProc>
  </rProtDe>
</rRetEnviEventoDe>
""".strip()

    result_code, result_message, status, protocol = _normalize_response(response_raw)

    assert result_code == "1299"
    assert result_message == "Error de validación"
    assert status == "rejected"
    assert protocol is None


def test_build_enviar_evento_request_xml_keeps_unprefixed_signature() -> None:
    group_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<gGroupGesEve xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <rGesEve>
    <rEve Id="1234567890">
      <dFecFirma>2026-04-27T00:00:00</dFecFirma>
      <dVerFor>150</dVerFor>
      <gGroupTiEvt>
        <rGeVeCan>
          <Id>01800241355001001000000012026042711234567893</Id>
          <mOtEve>Prueba cancelacion</mOtEve>
        </rGeVeCan>
      </gGroupTiEvt>
    </rEve>
    <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
      <SignedInfo/>
    </Signature>
  </rGesEve>
</gGroupGesEve>
""".strip()

    request_xml = _build_enviar_evento_request_xml(d_id=123, event_group_xml=group_xml)

    assert "<rEnviEventoDe" in request_xml
    assert "<dId>123</dId>" in request_xml
    assert "<gGroupGesEve" in request_xml
    assert (
        'xsi:schemaLocation="http://ekuatia.set.gov.py/sifen/xsd '
        'siRecepEvento_v150.xsd"'
        in request_xml
    )
    assert '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">' in request_xml
    assert ":Signature" not in request_xml


def test_event_xml_survives_envelope_wrap() -> None:
    group_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gGroupGesEve xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
        '<rGesEve><rEve Id="1234567890"><dFecFirma>2026-04-27T00:00:00</dFecFirma>'
        "<dVerFor>150</dVerFor><gGroupTiEvt><rGeVeCan>"
        "<Id>01800241355001001000000012026042711234567893</Id>"
        "<mOtEve>Prueba cancelacion</mOtEve>"
        "</rGeVeCan></gGroupTiEvt></rEve>"
        '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignedInfo/></Signature>'
        "</rGesEve></gGroupGesEve>"
    )

    request_xml = _build_enviar_evento_request_xml(d_id=123, event_group_xml=group_xml)
    expected_group_xml = (
        '<gGroupGesEve xmlns="http://ekuatia.set.gov.py/sifen/xsd" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://ekuatia.set.gov.py/sifen/xsd '
        'siRecepEvento_v150.xsd">'
        '<rGesEve><rEve Id="1234567890"><dFecFirma>2026-04-27T00:00:00</dFecFirma>'
        "<dVerFor>150</dVerFor><gGroupTiEvt><rGeVeCan>"
        "<Id>01800241355001001000000012026042711234567893</Id>"
        "<mOtEve>Prueba cancelacion</mOtEve>"
        "</rGeVeCan></gGroupTiEvt></rEve>"
        '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignedInfo/></Signature>'
        "</rGesEve></gGroupGesEve>"
    )

    assert expected_group_xml in request_xml


_GROUP_XML = (
    '<gGroupGesEve xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
    '<rGesEve><rEve Id="1234567890"/></rGesEve></gGroupGesEve>'
)


def _event(payload: dict | None) -> SimpleNamespace:
    return SimpleNamespace(input_payload=payload)


def _gateway_without_signature_check(monkeypatch, verified: list[str]):
    monkeypatch.setattr(
        event_module,
        "_verify_event_signature_locally",
        lambda *, request_xml, **_: verified.append(request_xml),
    )
    return KilaSifenEventGateway("test")


def test_prepare_event_wraps_the_signed_group_with_the_dId_that_travels(
    monkeypatch,
) -> None:
    verified: list[str] = []
    monkeypatch.setattr(event_module, "_generate_id", lambda: 2604271)
    gateway = _gateway_without_signature_check(monkeypatch, verified)

    prepared = gateway.prepare_event(
        event=_event({"event_xml": _GROUP_XML}),
        emitter=SimpleNamespace(tax_environment="test"),
        certificate_bytes=b"certificate",
        certificate_password="password",
    )

    assert prepared.signed_xml == _GROUP_XML
    assert "<dId>2604271</dId>" in prepared.request_xml
    assert verified == [prepared.request_xml]


def test_prepare_event_refuses_an_emitter_from_another_environment(
    monkeypatch,
) -> None:
    gateway = _gateway_without_signature_check(monkeypatch, [])

    with pytest.raises(SifenValidationError, match="tax environment"):
        gateway.prepare_event(
            event=_event({"event_xml": _GROUP_XML}),
            emitter=SimpleNamespace(tax_environment="production"),
            certificate_bytes=b"certificate",
            certificate_password="password",
        )


def test_submit_prepared_sends_the_stored_request_unchanged(monkeypatch) -> None:
    sent: list[str] = []

    def fake_raw_submit(*, request_xml: str, **kwargs) -> str:
        del kwargs
        sent.append(request_xml)
        return (
            '<rRetEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
            "<gResProcEVe><dEstRes>Aprobado</dEstRes><dProtAut>77</dProtAut>"
            "<gResProc><dCodRes>0600</dCodRes><dMsgRes>ok</dMsgRes></gResProc>"
            "</gResProcEVe></rRetEnviEventoDe>"
        )

    monkeypatch.setattr(event_module, "_submit_event_raw", fake_raw_submit)

    outcome = KilaSifenEventGateway("test").submit_prepared(
        request_xml="<rEnviEventoDe><dId>9</dId></rEnviEventoDe>",
        emitter=SimpleNamespace(tax_environment="test"),
        certificate_bytes=b"certificate",
        certificate_password="password",
    )

    assert sent == ["<rEnviEventoDe><dId>9</dId></rEnviEventoDe>"]
    assert outcome.status == "approved"
    assert outcome.protocol == "77"


@pytest.mark.parametrize(
    ("body", "actual_root"),
    [
        ("<html><body>502 Bad Gateway</body></html>", "html"),
        (
            '<env:Fault xmlns:env="http://www.w3.org/2003/05/soap-envelope">'
            "<env:Reason>boom</env:Reason></env:Fault>",
            "Fault",
        ),
        ("respuesta truncada <rRetEnviEventoDe", "invalid_xml"),
    ],
)
def test_an_unreadable_event_answer_is_uncertain_not_a_validation_error(
    body: str,
    actual_root: str,
) -> None:
    with pytest.raises(SifenUnexpectedResponseError) as raised:
        _normalize_response(body)

    assert raised.value.expected_root == "rRetEnviEventoDe"
    assert raised.value.actual_root == actual_root
