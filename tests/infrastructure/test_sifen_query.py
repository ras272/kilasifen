"""siConsDE through the live gateway, with a transport double (DECISIONES F62)."""

from __future__ import annotations

from xml.sax.saxutils import escape

import pytest

from kilasifen.engine.de.bindings.v150.ws_si_cons_de_v141 import (
    REnviConsDeResponse,
)
from kilasifen.engine.transmision.base import _parsear_respuesta
from kilasifen.infrastructure.sifen import query as query_module
from kilasifen.infrastructure.sifen.query import (
    QUERY_ERROR,
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    KilaSifenQueryGateway,
)

_NS = "http://ekuatia.set.gov.py/sifen/xsd"
_CDC = "01800241355001001000000012026042711234567893"


class _Emitter:
    tax_environment = "test"


class _FakeConsulta:
    """Stands for ``ConsultaSIFEN``: records what travels, answers ``body``."""

    body: bytes = b""
    sent: list[tuple[str, str]] = []

    def __init__(self, **kwargs) -> None:
        del kwargs

    def __enter__(self) -> _FakeConsulta:
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def _serialize(self, request) -> str:
        return f"<rEnviConsDeRequest><dId>{request.dId}</dId>" + (
            f"<dCDC>{request.dCDC}</dCDC></rEnviConsDeRequest>"
        )

    def _send_raw_xml(self, service: str, xml: str) -> bytes:
        type(self).sent.append((service, xml))
        return type(self).body

    def _como_respuesta(self, body: bytes, clazz: type):
        return _parsear_respuesta(body, clazz)


@pytest.fixture
def consulta(monkeypatch: pytest.MonkeyPatch) -> type[_FakeConsulta]:
    _FakeConsulta.sent = []
    monkeypatch.setattr(query_module, "ConsultaSIFEN", _FakeConsulta)
    monkeypatch.setattr(query_module, "_generate_query_id", lambda: 4242)
    return _FakeConsulta


def _response(code: str, message: str, content: str | None = None) -> bytes:
    container = f"<xContenDE>{escape(content)}</xContenDE>" if content else ""
    return (
        f'<rEnviConsDeResponse xmlns="{_NS}">'
        "<dFecProc>2026-10-01T10:00:00-03:00</dFecProc>"
        f"<dCodRes>{code}</dCodRes><dMsgRes>{message}</dMsgRes>{container}"
        "</rEnviConsDeResponse>"
    ).encode("utf-8")


def _query(gateway: KilaSifenQueryGateway):
    return gateway.query_document(
        emitter=_Emitter(),
        certificate_bytes=b"certificate",
        certificate_password="password",
        cdc=_CDC,
    )


def test_0422_is_found_and_the_container_is_read(consulta) -> None:
    consulta.body = _response(
        "0422",
        "CDC encontrado",
        f'<rContDe><rDE xmlns="{_NS}"><DE Id="{_CDC}"/></rDE>'
        "<dProtAut>1122334455</dProtAut>"
        "<xContEv><rContEv><xEvento><rGeVeCan>"
        f"<Id>{_CDC}</Id><mOtEve>Error de carga</mOtEve></rGeVeCan></xEvento>"
        "<rResEnviEventoDe><gResProcEVe><dEstRes>Aprobado</dEstRes>"
        "<dProtAut>9988</dProtAut></gResProcEVe></rResEnviEventoDe>"
        "</rContEv></xContEv></rContDe>",
    )

    outcome = _query(KilaSifenQueryGateway())

    assert outcome.status == QUERY_FOUND
    assert outcome.protocol == "1122334455"
    assert outcome.cancelled is True
    assert outcome.processed_at is not None


def test_0420_means_not_found_or_not_approved(consulta) -> None:
    # Guia de Mejores Practicas DNIT oct-2024 (p. 12).
    consulta.body = _response(
        "0420", "Documento No Existe en SIFEN o ha sido Rechazado"
    )

    outcome = _query(KilaSifenQueryGateway())

    assert outcome.status == QUERY_NOT_FOUND_OR_NOT_APPROVED
    assert outcome.container is None and outcome.cancelled is False


@pytest.mark.parametrize("code", ["0421", "0160", "0380"])
def test_any_other_code_is_an_error_not_a_not_found(consulta, code: str) -> None:
    consulta.body = _response(code, "error")

    assert _query(KilaSifenQueryGateway()).status == QUERY_ERROR


def test_the_audited_request_is_exactly_the_one_sent(consulta) -> None:
    consulta.body = _response("0420", "No existe")

    outcome = _query(KilaSifenQueryGateway())

    assert consulta.sent == [("cons_de", outcome.request_xml)]
    assert "<dId>4242</dId>" in outcome.request_xml
    assert outcome.response_raw == consulta.body.decode("utf-8")


def test_a_malformed_cdc_is_refused_before_anything_travels(consulta) -> None:
    with pytest.raises(ValueError, match="44"):
        KilaSifenQueryGateway().query_document(
            emitter=_Emitter(),
            certificate_bytes=b"certificate",
            certificate_password="password",
            cdc="123",
        )
    assert consulta.sent == []


def test_the_binding_still_reads_the_answer() -> None:
    parsed = _parsear_respuesta(_response("0420", "No existe"), REnviConsDeResponse)

    assert parsed.dCodRes == "0420"
