from unittest.mock import MagicMock, patch

from kilasifen.infrastructure.sifen.engine import (
    KilaSifenDocumentTransport,
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


def test_live_document_transport_disables_automatic_mutation_retries() -> None:
    response = _FakeResponse(
        _FakeProt(
            status="Aprobado",
            result=_FakeResult(code="0260", message="DE aprobado"),
        )
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.enviar_de_xml.return_value = response

    with patch(
        "kilasifen.infrastructure.sifen.engine.SifenClient",
        return_value=client,
    ) as client_class:
        transport = KilaSifenDocumentTransport()
        transport.serializer = MagicMock()
        transport.serializer.render.return_value = "<response />"

        outcome = transport.submit(
            signed_xml="<rDE />",
            tax_environment="test",
            certificate_bytes=b"certificate",
            certificate_password="password",
        )

    client_class.assert_called_once_with(
        ambiente=2,
        pkcs12_data=b"certificate",
        pkcs12_password="password",
        max_retries=0,
    )
    client.enviar_de_xml.assert_called_once_with("<rDE />")
    assert outcome.sifen_status == "approved"
