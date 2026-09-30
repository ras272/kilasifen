"""Tests for the high-level SDK client facade."""

from unittest.mock import MagicMock, patch

import pytest

from kilasifen.engine.sdk.client import SifenClient


def test_sifen_client_builds_internal_services_with_shared_config():
    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE") as de_cls,
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN") as cons_cls,
        patch("kilasifen.engine.sdk.client.TransmissaoEvento") as evt_cls,
    ):
        SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
            timeout=15,
            max_retries=4,
            retry_backoff=0.5,
        )

    query_kwargs = {
        "ambiente": 2,
        "pkcs12_data": b"cert",
        "pkcs12_password": "pwd",
        "timeout": 15,
        "max_retries": 4,
        "retry_backoff": 0.5,
    }
    mutation_kwargs = {**query_kwargs, "max_retries": 0}
    de_cls.assert_called_once_with(**mutation_kwargs)
    cons_cls.assert_called_once_with(**query_kwargs)
    evt_cls.assert_called_once_with(**mutation_kwargs)


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
    cons.consultar_dte_async.return_value = "cons-dte-async"
    evt.enviar_evento.return_value = "evt-ok"

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
        patch(
            "kilasifen.engine.sdk.client.poll_dte_async_status",
            return_value="polled-async",
        ) as poll_async,
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
        assert client.consultar_dte_async("payload-async") == "cons-dte-async"
        assert (
            client.poll_dte_async(
                fetch_status="fetch-fn",
                protocol_id="123",
            )
            == "polled-async"
        )
        assert client.enviar_evento("evento") == "evt-ok"

    de.enviar_de.assert_called_once_with("rde", sign=False)
    de.enviar_lote.assert_called_once_with(["rde1", "rde2"], lote_id=12, sign=False)
    cons.consultar_de.assert_called_once_with("1" * 44)
    cons.consultar_lote.assert_called_once_with(123)
    cons.consultar_ruc.assert_called_once_with("80069563")
    cons.consultar_dte.assert_called_once_with("payload")
    cons.consultar_dte_async.assert_called_once_with("payload-async")
    poll_async.assert_called_once()
    evt.enviar_evento.assert_called_once_with("evento")


def test_sifen_client_enviar_lote_y_esperar_uses_polling_helper():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    envio_lote = MagicMock(dProtConsLote="123456")
    de.enviar_lote.return_value = envio_lote

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
        patch(
            "kilasifen.engine.sdk.client.poll_lote_status",
            return_value="lote-final",
        ) as poll_lote,
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )
        result = client.enviar_lote_y_esperar(
            lista_rde=["rde"],
            lote_id=12,
            sign=False,
        )

    assert result == "lote-final"
    de.enviar_lote.assert_called_once_with(
        ["rde"],
        lote_id=12,
        sign=False,
    )
    poll_lote.assert_called_once()


def test_sifen_client_consultar_dte_async_y_esperar_returns_both():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    async_response = MagicMock(dProtConsDTEAsync="ABC123")
    cons.consultar_dte_async.return_value = async_response

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
        patch(
            "kilasifen.engine.sdk.client.poll_dte_async_status",
            return_value="estado-final",
        ) as poll_async,
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )
        response, status = client.consultar_dte_async_y_esperar(
            consulta_dte_async="payload",
            fetch_status="fetch-fn",
        )

    assert response is async_response
    assert status == "estado-final"
    cons.consultar_dte_async.assert_called_once_with("payload")
    poll_async.assert_called_once()


def test_sifen_client_consultar_dte_async_y_esperar_requires_protocol():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()
    cons.consultar_dte_async.return_value = MagicMock(dProtConsDTEAsync="")

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )
        with pytest.raises(ValueError, match="dProtConsDTEAsync"):
            client.consultar_dte_async_y_esperar(
                consulta_dte_async="payload",
                fetch_status="fetch-fn",
            )


def test_sifen_client_enviar_lote_y_esperar_requires_protocol():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()
    de.enviar_lote.return_value = MagicMock(dProtConsLote=None)

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )
        with pytest.raises(ValueError, match="dProtConsLote"):
            client.enviar_lote_y_esperar(lista_rde=["rde"])


def test_sifen_client_wraps_fiscal_generators():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
        patch(
            "kilasifen.engine.sdk.client._generate_cdc",
            return_value="CDC-OK",
        ) as gen_cdc,
        patch(
            "kilasifen.engine.sdk.client._generate_dcarqr",
            return_value="QRCODE-OK",
        ) as gen_qr,
        patch(
            "kilasifen.engine.sdk.client._generate_dcarqr_from_signed_xml",
            return_value="QRCODE-XML-OK",
        ) as gen_qr_xml,
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )
        cdc = client.generar_cdc(foo="bar")
        qr = client.generar_dcarqr(foo="bar")
        qr_xml = client.generar_dcarqr_desde_xml_firmado(foo="bar")

    assert cdc == "CDC-OK"
    assert qr == "QRCODE-OK"
    assert qr_xml == "QRCODE-XML-OK"
    gen_cdc.assert_called_once_with(foo="bar")
    gen_qr.assert_called_once_with(foo="bar")
    gen_qr_xml.assert_called_once_with(foo="bar")


def test_sifen_client_wraps_kude_helpers():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
        patch(
            "kilasifen.engine.sdk.client._render_kude_html",
            return_value="<html>kude</html>",
        ) as render_kude,
        patch(
            "kilasifen.engine.sdk.client._save_kude_html",
            return_value="out.html",
        ) as save_kude,
    ):
        client = SifenClient(
            ambiente=2,
            pkcs12_data=b"cert",
            pkcs12_password="pwd",
        )
        html = client.render_kude_html("rde", title="Doc")
        out = client.save_kude_html(
            "rde",
            "tmp/kude.html",
            title="Doc",
            encoding="utf-8",
        )

    assert html == "<html>kude</html>"
    assert out == "out.html"
    render_kude.assert_called_once_with("rde", title="Doc")
    save_kude.assert_called_once_with(
        "rde",
        "tmp/kude.html",
        title="Doc",
        encoding="utf-8",
    )


def test_sifen_client_close_is_idempotent():
    de = MagicMock()
    cons = MagicMock()
    evt = MagicMock()

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
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

    with (
        patch("kilasifen.engine.sdk.client.TransmissaoDE", return_value=de),
        patch("kilasifen.engine.sdk.client.ConsultaSIFEN", return_value=cons),
        patch("kilasifen.engine.sdk.client.TransmissaoEvento", return_value=evt),
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
