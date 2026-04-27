from kilasifen.infrastructure.sifen.event import (
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
      <dCodRes>0300</dCodRes>
      <dMsgRes>Evento aprobado</dMsgRes>
    </gResProc>
  </gResProcEVe>
</rRetEnviEventoDe>
""".strip()

    result_code, result_message, status, protocol = _normalize_response(response_raw)

    assert result_code == "0300"
    assert result_message == "Evento aprobado"
    assert status == "approved"
    assert protocol == "123456789"


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
