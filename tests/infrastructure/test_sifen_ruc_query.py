"""siConsRUC through the live gateway, with a transport double (MT v150 §9.6)."""

from __future__ import annotations

import pytest

from kilasifen.engine.de.bindings.v150.ws_si_cons_ruc_v141 import RResEnviConsRuc
from kilasifen.engine.sdk.errors import (
    SifenTimeoutError,
    SifenUnexpectedResponseError,
)
from kilasifen.engine.transmision.base import _parsear_respuesta
from kilasifen.infrastructure.sifen import query as query_module
from kilasifen.infrastructure.sifen.query import (
    RUC_ERROR,
    RUC_FOUND,
    RUC_NOT_FOUND,
    RUC_RETRY_PAUSES_SECONDS,
    KilaSifenQueryGateway,
)
from kilasifen.testing.typed_documents import (
    FICTIONAL_EMITTER_DV,
    FICTIONAL_EMITTER_RUC,
)

_NS = "http://ekuatia.set.gov.py/sifen/xsd"
_TAXPAYER = (
    f"<xContRUC><dRUCCons>{FICTIONAL_EMITTER_RUC}</dRUCCons>"
    "<dRazCons>CONTRIBUYENTE FICTICIO SA</dRazCons>"
    "<dCodEstCons>ACT</dCodEstCons><dDesEstCons>ACTIVO</dDesEstCons>"
    "<dRUCFactElec>S</dRUCFactElec></xContRUC>"
)


class _Emitter:
    tax_environment = "test"


class _FakeConsulta:
    """Stands for ``ConsultaSIFEN``: answers each RUC query from ``answers``."""

    answers: list[bytes | Exception] = []
    asked: list[str] = []

    def __init__(self, **kwargs) -> None:
        del kwargs

    def __enter__(self) -> _FakeConsulta:
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def consultar_ruc(self, ruc: str) -> RResEnviConsRuc:
        type(self).asked.append(ruc)
        answer = type(self).answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _parsear_respuesta(answer, RResEnviConsRuc)


@pytest.fixture
def consulta(monkeypatch: pytest.MonkeyPatch) -> type[_FakeConsulta]:
    _FakeConsulta.answers = []
    _FakeConsulta.asked = []
    monkeypatch.setattr(query_module, "ConsultaSIFEN", _FakeConsulta)
    return _FakeConsulta


def _answer(code: str, message: str, taxpayer: str = "") -> bytes:
    return (
        f'<rResEnviConsRUC xmlns="{_NS}"><dCodRes>{code}</dCodRes>'
        f"<dMsgRes>{message}</dMsgRes>{taxpayer}</rResEnviConsRUC>"
    ).encode("utf-8")


def _malformed(message: str = "XML Mal Formado.") -> SifenUnexpectedResponseError:
    # How the test environment answered valid queries (HTTP 400, rRetEnviDe).
    return SifenUnexpectedResponseError(
        expected_root="rResEnviConsRUC",
        actual_root="rRetEnviDe",
        code="0160",
        response_message=message,
    )


def _query(pauses: list[float]):
    gateway = KilaSifenQueryGateway(sleep=pauses.append)
    return gateway.query_ruc(
        emitter=_Emitter(),
        certificate_bytes=b"certificate",
        certificate_password="password",
        ruc=f"{FICTIONAL_EMITTER_RUC}-{FICTIONAL_EMITTER_DV}",
    )


def test_0502_returns_the_taxpayer_with_its_computed_dv(consulta) -> None:
    consulta.answers = [_answer("0502", "RUC encontrado", _TAXPAYER)]

    outcome = _query([])

    assert outcome.status == RUC_FOUND
    assert (outcome.taxpayer_ruc, outcome.taxpayer_dv) == (
        FICTIONAL_EMITTER_RUC,
        FICTIONAL_EMITTER_DV,
    )
    assert outcome.taxpayer_legal_name == "CONTRIBUYENTE FICTICIO SA"
    assert (outcome.taxpayer_state_code, outcome.taxpayer_state) == ("ACT", "ACTIVO")
    assert outcome.electronic_taxpayer is True


def test_0500_means_the_ruc_does_not_exist(consulta) -> None:
    consulta.answers = [_answer("0500", "RUC no existe")]

    outcome = _query([])

    assert outcome.status == RUC_NOT_FOUND
    assert outcome.taxpayer_ruc is None and outcome.taxpayer_dv is None


@pytest.mark.parametrize("code", ["0501", "0502", "0999"])
def test_any_other_answer_without_taxpayer_is_an_error(consulta, code: str) -> None:
    consulta.answers = [_answer(code, "sin datos")]

    assert _query([]).status == RUC_ERROR


def test_a_bare_0160_is_asked_again_after_a_pause(consulta) -> None:
    consulta.answers = [
        _malformed(),
        _malformed(),
        _answer("0502", "RUC encontrado", _TAXPAYER),
    ]
    pauses: list[float] = []

    outcome = _query(pauses)

    assert outcome.status == RUC_FOUND
    assert pauses == list(RUC_RETRY_PAUSES_SECONDS)
    assert len(consulta.asked) == 3


def test_the_query_gives_up_after_its_last_attempt(consulta) -> None:
    consulta.answers = [_malformed() for _ in range(len(RUC_RETRY_PAUSES_SECONDS) + 1)]
    pauses: list[float] = []

    with pytest.raises(SifenUnexpectedResponseError):
        _query(pauses)

    assert pauses == list(RUC_RETRY_PAUSES_SECONDS)
    assert consulta.answers == []


@pytest.mark.parametrize(
    "failure",
    [
        _malformed("XML malformado: [El valor del elemento: dRUCCons es invalido]"),
        SifenUnexpectedResponseError(
            expected_root="rResEnviConsRUC", actual_root="Fault"
        ),
        SifenTimeoutError("timeout"),
    ],
    ids=["0160-with-detail", "soap-fault", "timeout"],
)
def test_other_failures_are_raised_at_once(consulta, failure: Exception) -> None:
    consulta.answers = [failure, _answer("0502", "RUC encontrado", _TAXPAYER)]
    pauses: list[float] = []

    with pytest.raises(type(failure)):
        _query(pauses)

    assert pauses == []
    assert len(consulta.asked) == 1
