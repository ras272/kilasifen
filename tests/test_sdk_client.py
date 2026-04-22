"""Tests for the high-level SDK client facade."""

from unittest.mock import MagicMock, patch

from pysifen.sdk.client import SifenClient


def test_sifen_client_builds_internal_services_with_shared_config():
    with patch("pysifen.sdk.client.TransmissaoDE") as de_cls, patch(
        "pysifen.sdk.client.ConsultaSIFEN"
    ) as cons_cls, patch(
        "pysifen.sdk.client.TransmissaoEvento"
    ) as evt_cls:
        SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
            timeout=15,
            max_retries=4,
            retry_backoff=0.5,
        )

    expected_kwargs = {
        "ambiente": 2,
        "pkcs12_data": b"cert",
        "pkcs12_password": "pwd",
        "timeout": 15,
        "max_retries": 4,
        "retry_backoff": 0.5,
    }
    de_cls.assert_called_once_with(**expected_kwargs)
    cons_cls.assert_called_once_with(**expected_kwargs)
    evt_cls.assert_called_once_with(**expected_kwargs)


def test_sifen_client_delegates_all_operations():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    de.enviar_de.return_value = "de-ok"
    de.enviar_lote.return_value = "lote-ok"
    cons.consultar_de.return_value = "cons-de"
    cons.consultar_lote.return_value = "cons-lote"
    cons.consultar_ruc.return_value = "cons-ruc"
    cons.consultar_dte.return_value = "cons-dte"
    evt.enviar_evento.return_value = "evt-ok"

    with patch(
        "pysifen.sdk.client.TransmissaoDE", return_value=de
    ), patch(
        "pysifen.sdk.client.ConsultaSIFEN", return_value=cons
    ), patch(
        "pysifen.sdk.client.TransmissaoEvento", return_value=evt
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )

        assert client.enviar_de("rde", sign=False) == "de-ok"
        assert (
            client.enviar_lote(
                ["rde1", "rde2"],
                lote_id=12,
                sign=False,
            )
            == "lote-ok"
        )
        assert client.consultar_de("1" * 44) == "cons-de"
        assert client.consultar_lote(123) == "cons-lote"
        assert client.consultar_ruc("80069563") == "cons-ruc"
        assert client.consultar_dte("payload") == "cons-dte"
        assert client.enviar_evento("evento") == "evt-ok"

    de.enviar_de.assert_called_once_with("rde", sign=False)
    de.enviar_lote.assert_called_once_with(
        ["rde1", "rde2"], lote_id=12, sign=False
    )
    cons.consultar_de.assert_called_once_with("1" * 44)
    cons.consultar_lote.assert_called_once_with(123)
    cons.consultar_ruc.assert_called_once_with("80069563")
    cons.consultar_dte.assert_called_once_with("payload")
    evt.enviar_evento.assert_called_once_with("evento")


def test_sifen_client_close_is_idempotent():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    with patch(
        "pysifen.sdk.client.TransmissaoDE", return_value=de
    ), patch(
        "pysifen.sdk.client.ConsultaSIFEN", return_value=cons
    ), patch(
        "pysifen.sdk.client.TransmissaoEvento", return_value=evt
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )

        client.close()
        client.close()

    de.close.assert_called_once()
    cons.close.assert_called_once()
    evt.close.assert_called_once()


def test_sifen_client_context_manager_closes_services():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    with patch(
        "pysifen.sdk.client.TransmissaoDE", return_value=de
    ), patch(
        "pysifen.sdk.client.ConsultaSIFEN", return_value=cons
    ), patch(
        "pysifen.sdk.client.TransmissaoEvento", return_value=evt
    ):
        with SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        ) as client:
            assert isinstance(client, SifenClient)

    de.close.assert_called_once()
    cons.close.assert_called_once()
    evt.close.assert_called_once()
