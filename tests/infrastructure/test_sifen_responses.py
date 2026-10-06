"""siConsDE containers and DE facts (DECISIONES F62, F71; MT v150 §9.4.3)."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from kilasifen.domain.documents.models import Document
from kilasifen.infrastructure.sifen.de_facts import (
    approval_lower_bound,
    read_de_facts,
)
from kilasifen.infrastructure.sifen.responses import read_document_container

_NS = "http://ekuatia.set.gov.py/sifen/xsd"
_CDC = "01800241355001001000000012026042711234567893"
_RDE = (
    f'<rDE xmlns="{_NS}"><dVerFor>150</dVerFor><DE Id="{_CDC}">'
    "<dFecFirma>2026-10-01T09:00:00</dFecFirma>"
    "<gTimb><dNumTim>12345678</dNumTim></gTimb>"
    "<gDatGralOpe><dFeEmiDE>2026-09-30T18:30:00</dFeEmiDE></gDatGralOpe>"
    "</DE></rDE>"
)
_CANCELLATION = (
    "<xContEv><rContEv>"
    "<xEvento><rEve Id=\"1\"><gGroupTiEvt>"
    f"<rGeVeCan><Id>{_CDC}</Id><mOtEve>Error de carga</mOtEve></rGeVeCan>"
    "</gGroupTiEvt></rEve></xEvento>"
    "<rResEnviEventoDe><gResProcEVe><dEstRes>Aprobado</dEstRes>"
    "<dProtAut>9876543210</dProtAut><id>1</id>"
    "<gResProc><dCodRes>0600</dCodRes><dMsgRes>Evento registrado correctamente"
    "</dMsgRes></gResProc></gResProcEVe></rResEnviEventoDe>"
    "</rContEv></xContEv>"
)


def _query_response(content: str, *, escaped: bool) -> bytes:
    body = escape(content) if escaped else content
    return (
        f'<rEnviConsDeResponse xmlns="{_NS}">'
        "<dFecProc>2026-10-01T10:00:00-03:00</dFecProc>"
        "<dCodRes>0422</dCodRes><dMsgRes>CDC encontrado</dMsgRes>"
        f"<xContenDE>{body}</xContenDE>"
        "</rEnviConsDeResponse>"
    ).encode("utf-8")


def test_an_escaped_container_yields_the_dte_its_protocol_and_its_events() -> None:
    container = read_document_container(
        _query_response(
            f"<rContDe>{_RDE}<dProtAut>1122334455</dProtAut>{_CANCELLATION}</rContDe>",
            escaped=True,
        )
    )

    assert container is not None
    assert container.protocol == "1122334455"
    assert container.document_xml is not None and _CDC in container.document_xml
    cancellation = container.cancellation_for(_CDC)
    assert cancellation is not None
    assert cancellation.protocol == "9876543210"
    assert cancellation.state_text == "Aprobado"


def test_an_embedded_container_is_read_the_same_way() -> None:
    container = read_document_container(
        _query_response(
            f"<rContDe>{_RDE}<dProtAut>1122334455</dProtAut>{_CANCELLATION}</rContDe>",
            escaped=False,
        )
    )

    assert container is not None
    assert container.has_cancellation(_CDC)


def test_a_container_without_events_has_no_cancellation() -> None:
    container = read_document_container(
        _query_response(
            f"<rContDe>{_RDE}<dProtAut>1122334455</dProtAut></rContDe>",
            escaped=True,
        )
    )

    assert container is not None
    assert container.events == ()
    assert not container.has_cancellation(_CDC)


#: Fictional CDCs (emitter 44444401-7) for the layout seen in SIFEN TEST.
_CDC_TEST = "01444444017001001000010222026100611589812124"
_CDC_OTHER = "01444444017001001000010322026100612660564052"


def _event_group(cdc: str, *, protocol: str, kind: str = "rGeVeCan") -> str:
    # Layout observed in the test environment on 2026-10-06: the signed event
    # repeats its XML declaration inside xEvento and its answer travels next
    # to it, with whitespace between the elements.
    return (
        "\n\t<rContEv>\n\t\t<xEvento>\n\t\t\t"
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rGesEve xmlns="{_NS}"><rEve Id="9106431971">'
        "<dFecFirma>2026-10-06T12:12:17</dFecFirma><dVerFor>150</dVerFor>"
        f"<gGroupTiEvt><{kind}><Id>{cdc}</Id><mOtEve>Prueba de cancelacion"
        f"</mOtEve></{kind}></gGroupTiEvt></rEve></rGesEve>\n\t\t</xEvento>"
        "\n\t\t<rResEnviEventoDe>\n\t\t\t<rRetEnviEventoDe>"
        "<dFecProc>2026-10-06T12:12:19</dFecProc><gResProcEVe>"
        f"<dEstRes>Aprobado</dEstRes><dProtAut>{protocol}</dProtAut>"
        "<gResProc><dCodRes>0600</dCodRes><dMsgRes>Se encontro el evento"
        "</dMsgRes></gResProc></gResProcEVe></rRetEnviEventoDe>"
        "\n\t\t</rResEnviEventoDe>\n\t</rContEv>"
    )


def _test_environment_container(events: str) -> str:
    rde = _RDE.replace(_CDC, _CDC_TEST)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>{rde}\n'
        f"<dProtAut>50202476</dProtAut>\n<xContEv>{events}\n</xContEv> "
    )


def test_the_container_of_the_test_environment_is_read() -> None:
    # No rContDe, rDE/dProtAut/xContEv as siblings and a second XML
    # declaration inside xEvento: an uncertain cancellation was not found.
    container = read_document_container(
        _query_response(
            _test_environment_container(_event_group(_CDC_TEST, protocol="1166737")),
            escaped=True,
        )
    )

    assert container is not None
    assert container.protocol == "50202476"
    assert container.document_xml is not None and _CDC_TEST in container.document_xml
    cancellation = container.cancellation_for(_CDC_TEST)
    assert cancellation is not None
    assert cancellation.protocol == "1166737"
    assert cancellation.state_text == "Aprobado"


def test_an_empty_xcontev_of_the_test_environment_has_no_events() -> None:
    container = read_document_container(
        _query_response(_test_environment_container(""), escaped=True)
    )

    assert container is not None
    assert container.protocol == "50202476"
    assert container.events == ()


def test_each_event_keeps_the_protocol_of_its_own_answer() -> None:
    container = read_document_container(
        _query_response(
            _test_environment_container(
                _event_group(_CDC_OTHER, protocol="1111111", kind="rGeVeNotRec")
                + _event_group(_CDC_TEST, protocol="2222222")
            ),
            escaped=True,
        )
    )

    assert container is not None
    assert [event.protocol for event in container.events] == ["1111111", "2222222"]
    cancellation = container.cancellation_for(_CDC_TEST)
    assert cancellation is not None and cancellation.protocol == "2222222"


def test_embedded_siblings_without_rcontde_are_read() -> None:
    rde = _RDE.replace(_CDC, _CDC_TEST)
    container = read_document_container(
        _query_response(
            f"{rde}<dProtAut>50202476</dProtAut>"
            f"<xContEv>{_event_group(_CDC_TEST, protocol='1166737')}</xContEv>"
            .replace('<?xml version="1.0" encoding="UTF-8"?>', ""),
            escaped=False,
        )
    )

    assert container is not None
    assert container.protocol == "50202476"
    assert container.has_cancellation(_CDC_TEST)


def test_an_escaped_xevento_is_read() -> None:
    event = (
        f'<rGesEve xmlns="{_NS}"><rEve Id="1"><gGroupTiEvt><rGeVeCan>'
        f"<Id>{_CDC_TEST}</Id><mOtEve>Prueba</mOtEve></rGeVeCan></gGroupTiEvt>"
        "</rEve></rGesEve>"
    )
    container = read_document_container(
        _query_response(
            f"<rContDe>{_RDE}<dProtAut>50202476</dProtAut><xContEv><rContEv>"
            f"<xEvento>{escape(event)}</xEvento></rContEv></xContEv></rContDe>",
            escaped=False,
        )
    )

    assert container is not None
    assert container.has_cancellation(_CDC_TEST)


def test_a_bare_rde_is_accepted_as_the_container() -> None:
    container = read_document_container(_query_response(_RDE, escaped=True))

    assert container is not None
    assert container.document_xml is not None
    assert container.protocol is None and container.events == ()


def test_an_answer_without_container_has_none() -> None:
    body = (
        f'<rEnviConsDeResponse xmlns="{_NS}">'
        "<dCodRes>0420</dCodRes><dMsgRes>No existe</dMsgRes>"
        "</rEnviConsDeResponse>"
    ).encode("utf-8")

    assert read_document_container(body) is None
    assert read_document_container(b"<not-xml") is None


def test_de_facts_are_read_as_paraguay_wall_time() -> None:
    facts = read_de_facts(_RDE)

    paraguay = timezone(timedelta(hours=-3))
    assert facts.signed_at == datetime(2026, 10, 1, 9, 0, tzinfo=paraguay)
    assert facts.issued_at == datetime(2026, 9, 30, 18, 30, tzinfo=paraguay)
    assert facts.timbrado == "12345678"
    assert read_de_facts(None).signed_at is None
    assert read_de_facts("<rDE").timbrado is None


def test_the_approval_lower_bound_is_the_later_of_signature_and_creation() -> None:
    signed_at_utc = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    document = _document(
        signed_xml=_RDE, created_at=signed_at_utc - timedelta(hours=1)
    )

    # dFecFirma 09:00 Paraguay = 12:00 UTC, later than the creation.
    assert approval_lower_bound(document) == signed_at_utc

    later_creation = replace(document, created_at=signed_at_utc + timedelta(hours=2))
    assert approval_lower_bound(later_creation) == signed_at_utc + timedelta(hours=2)

    unsigned = replace(document, signed_xml=None)
    assert approval_lower_bound(unsigned) == document.created_at


def _document(*, signed_xml: str | None, created_at: datetime) -> Document:
    return Document(
        id="document-1",
        emitter_id="emitter-1",
        external_id=None,
        idempotency_key=None,
        document_type="factura",
        payload_snapshot=None,
        generated_xml=None,
        signed_xml=signed_xml,
        sifen_request_xml=None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=_CDC,
        internal_status="approved",
        sifen_status="approved",
        sifen_result_code="0422",
        sifen_result_message=None,
        created_at=created_at,
        updated_at=created_at,
    )
