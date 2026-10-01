"""Smoke tests para errores tipados del SDK."""

import pytest

pytest.importorskip("requests", reason="requests not installed")


def test_error_hierarchy_exports():
    from kilasifen.engine.sdk import (
        SifenError,
        SifenRequestNotSentError,
        SifenSignatureError,
        SifenTimeoutError,
        SifenTransportClosedError,
        SifenTransportError,
        SifenUnexpectedResponseError,
        SifenValidationError,
    )

    assert issubclass(SifenValidationError, SifenError)
    assert issubclass(SifenSignatureError, SifenError)
    assert issubclass(SifenTransportError, SifenError)
    assert issubclass(SifenTransportClosedError, SifenTransportError)
    assert issubclass(SifenTimeoutError, SifenTransportError)
    assert issubclass(SifenUnexpectedResponseError, SifenTransportError)
    # Los manejadores existentes de SifenTransportError siguen atrapandolo.
    assert issubclass(SifenRequestNotSentError, SifenTransportError)
    assert not issubclass(SifenRequestNotSentError, SifenTimeoutError)


def test_unexpected_response_message_is_spanish_and_omits_the_body():
    from kilasifen.engine.sdk.errors import SifenUnexpectedResponseError

    error = SifenUnexpectedResponseError(
        expected_root="rRetEnviDe",
        actual_root="rResEnviConsRUC",
        code="0160",
        response_message="XML Mal Formado.",
        raw_body=b"<rResEnviConsRUC>Comercial Ficticia SA</rResEnviConsRUC>",
    )

    assert str(error) == (
        "Respuesta inesperada del SIFEN: se esperaba rRetEnviDe y se recibio "
        "rResEnviConsRUC (0160): XML Mal Formado."
    )
    assert error.args == (str(error),)
    assert error.raw_body == "<rResEnviConsRUC>Comercial Ficticia SA</rResEnviConsRUC>"


@pytest.mark.parametrize(
    "cuerpo, esperado",
    [
        (None, None),
        ("<a/>", "<a/>"),
        (b"\xff<a/>", "�<a/>"),
        (bytearray(b"<b/>"), "<b/>"),
    ],
    ids=["sin_cuerpo", "texto", "bytes_no_utf8", "bytearray"],
)
def test_unexpected_response_raw_body_is_text(cuerpo, esperado):
    from kilasifen.engine.sdk.errors import SifenUnexpectedResponseError

    error = SifenUnexpectedResponseError(
        expected_root="a", actual_root="invalid_xml", raw_body=cuerpo
    )
    assert error.raw_body == esperado


def test_unexpected_response_raw_body_is_truncated():
    from kilasifen.engine.sdk.errors import (
        MAX_CUERPO_CRUDO,
        SifenUnexpectedResponseError,
    )

    error = SifenUnexpectedResponseError(
        expected_root="a", actual_root="html", raw_body="y" * (MAX_CUERPO_CRUDO + 10)
    )
    assert error.raw_body == "y" * MAX_CUERPO_CRUDO


def test_sign_xml_wraps_unexpected_errors(monkeypatch):
    from kilasifen.engine.firma import sign_xml
    from kilasifen.engine.sdk.errors import SifenSignatureError

    def boom(*args, **kwargs):
        raise ValueError("invalid")

    monkeypatch.setattr(
        "cryptography.hazmat.primitives.serialization.pkcs12.load_key_and_certificates",
        boom,
    )

    with pytest.raises(SifenSignatureError) as excinfo:
        sign_xml("<root />", b"fake", "pass", "doc")

    assert isinstance(excinfo.value.__cause__, ValueError)


def test_transport_wraps_timeout(monkeypatch):
    from requests.exceptions import Timeout

    from kilasifen.engine.sdk.errors import SifenTimeoutError
    from kilasifen.engine.transmision.base import _create_transport

    transport = _create_transport("cert.pem", "key.pem")

    def boom(*args, **kwargs):
        raise Timeout("slow")

    monkeypatch.setattr(transport._session, "post", boom)

    with pytest.raises(SifenTimeoutError) as excinfo:
        transport.post("https://example.invalid", b"<xml />")

    assert isinstance(excinfo.value.__cause__, Timeout)


def test_transport_wraps_http_error(monkeypatch):
    from requests.exceptions import HTTPError

    from kilasifen.engine.sdk.errors import SifenTransportError
    from kilasifen.engine.transmision.base import _create_transport

    transport = _create_transport("cert.pem", "key.pem")

    class Response:
        content = b""

        def raise_for_status(self):
            raise HTTPError("500")

    monkeypatch.setattr(
        transport._session,
        "post",
        lambda *args, **kwargs: Response(),
    )

    with pytest.raises(SifenTransportError) as excinfo:
        transport.post("https://example.invalid", b"<xml />")

    assert isinstance(excinfo.value.__cause__, HTTPError)
