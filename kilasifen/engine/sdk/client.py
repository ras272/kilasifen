"""High-level SDK client facade for SIFEN operations."""

from __future__ import annotations

from kilasifen.engine.sdk.fiscal import (
    generate_cdc as _generate_cdc,
)
from kilasifen.engine.sdk.fiscal import (
    generate_dcarqr as _generate_dcarqr,
)
from kilasifen.engine.sdk.fiscal import (
    generate_dcarqr_from_signed_xml as _generate_dcarqr_from_signed_xml,
)
from kilasifen.engine.sdk.kude import (
    render_kude_html as _render_kude_html,
)
from kilasifen.engine.sdk.kude import (
    save_kude_html as _save_kude_html,
)
from kilasifen.engine.sdk.polling import (
    LoteResult,
    PollingConfig,
    poll_dte_async_status,
    poll_lote_status,
    require_lote_protocol,
)
from kilasifen.engine.transmision import (
    ConsultaSIFEN,
    TransmisionDE,
    TransmisionEvento,
)


class SifenClient:
    """Facade that exposes common SIFEN operations behind one client."""

    def __init__(
        self,
        ambiente: int,
        pkcs12_data: bytes,
        pkcs12_password: str,
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_backoff: float = 0.2,
    ):
        self._de = TransmisionDE(
            ambiente=ambiente,
            pkcs12_data=pkcs12_data,
            pkcs12_password=pkcs12_password,
            timeout=timeout,
            max_retries=0,
            retry_backoff=retry_backoff,
        )
        self._consulta = ConsultaSIFEN(
            ambiente=ambiente,
            pkcs12_data=pkcs12_data,
            pkcs12_password=pkcs12_password,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
        self._evento = TransmisionEvento(
            ambiente=ambiente,
            pkcs12_data=pkcs12_data,
            pkcs12_password=pkcs12_password,
            timeout=timeout,
            max_retries=0,
            retry_backoff=retry_backoff,
        )
        self._closed = False

    def enviar_de(self, rde, sign: bool = True):
        return self._de.enviar_de(rde, sign=sign)

    def enviar_de_xml(self, xml_de: str | bytes):
        return self._de.enviar_de_xml(xml_de)

    def enviar_lote(
        self,
        lista_rde: list,
        lote_id: int | None = None,
        sign: bool = True,
    ):
        return self._de.enviar_lote(
            lista_rde,
            lote_id=lote_id,
            sign=sign,
        )

    def enviar_lote_xml(self, lista_xml: list, lote_id: int | None = None):
        return self._de.enviar_lote_xml(lista_xml, lote_id=lote_id)

    def consultar_de(self, cdc: str):
        return self._consulta.consultar_de(cdc)

    def consultar_lote(self, prot_lote=None, *, cdc: str | None = None):
        return self._consulta.consultar_lote(prot_lote, cdc=cdc)

    def consultar_ruc(self, ruc: str):
        return self._consulta.consultar_ruc(ruc)

    def consultar_dte(self, consulta_dte):
        return self._consulta.consultar_dte(consulta_dte)

    def consultar_dte_async(self, consulta_dte_async):
        return self._consulta.consultar_dte_async(consulta_dte_async)

    def poll_dte_async(
        self,
        fetch_status,
        protocol_id: str,
        config: PollingConfig = PollingConfig(),
    ):
        return poll_dte_async_status(
            fetch_status,
            protocol_id,
            config=config,
        )

    def consultar_dte_async_y_esperar(
        self,
        consulta_dte_async,
        fetch_status,
        polling_config: PollingConfig = PollingConfig(),
    ):
        """Registra una consulta DTE asincronica y espera su resultado.

        EXPERIMENTAL: la consulta DTE no esta documentada por la SET (ver
        :func:`~kilasifen.engine.sdk.polling.poll_dte_async_status`).
        """
        async_response = self.consultar_dte_async(consulta_dte_async)
        protocol_id = str(
            getattr(async_response, "dProtConsDTEAsync", "") or ""
        ).strip()
        if not protocol_id:
            raise ValueError(
                "consulta_dte_async response must include dProtConsDTEAsync"
            )
        final_status = self.poll_dte_async(
            fetch_status=fetch_status,
            protocol_id=protocol_id,
            config=polling_config,
        )
        return async_response, final_status

    def enviar_lote_y_esperar(
        self,
        lista_rde: list,
        lote_id: int | None = None,
        sign: bool = True,
        polling_config: PollingConfig = PollingConfig(),
    ) -> LoteResult:
        """Envia un lote y espera su resultado consultandolo; bloquea.

        Solo consulta si la recepcion fue ``0300`` con numero de lote (MT
        sec. 12.3.2.3; Guia de mejores practicas, oct-2024, p. 9). Con los
        valores por defecto de :class:`PollingConfig` la primera consulta va
        a los 600 s y las siguientes cada 600 s; ante ``0364`` o pasadas
        48 h consulta cada CDC del lote con siConsDE.

        Raises:
            SifenRejectionError: si la recepcion no fue ``0300`` (por
                ejemplo, ``0301``); el lote no se consulta.
            SifenLoteError: si la recepcion ``0300`` no trae
                ``dProtConsLote`` o la consulta del lote devuelve un error.
            SifenTimeoutError: si se agota la espera configurada con el lote
                todavia en procesamiento.
        """
        envio = self.enviar_lote(
            lista_rde=lista_rde,
            lote_id=lote_id,
            sign=sign,
        )
        return poll_lote_status(
            consultar_lote=self.consultar_lote,
            prot_lote=require_lote_protocol(envio),
            config=polling_config,
            cdcs=_cdcs_del_lote(lista_rde),
            consultar_de=self.consultar_de,
        )

    def generar_cdc(self, **kwargs):
        """Convenience wrapper around SDK fiscal CDC generator."""
        return _generate_cdc(**kwargs)

    def generar_dcarqr(self, **kwargs):
        """Convenience wrapper around SDK fiscal dCarQR generator."""
        return _generate_dcarqr(**kwargs)

    def generar_dcarqr_desde_xml_firmado(self, **kwargs):
        """Build dCarQR using literal values from a signed DE XML."""
        return _generate_dcarqr_from_signed_xml(**kwargs)

    def render_kude_html(self, rde, *, title: str = "KuDE"):
        """Render a printable KuDE HTML."""
        return _render_kude_html(rde, title=title)

    def save_kude_html(
        self,
        rde,
        file_path,
        *,
        title: str = "KuDE",
        encoding: str = "utf-8",
    ):
        """Render and save KuDE HTML to disk."""
        return _save_kude_html(
            rde,
            file_path,
            title=title,
            encoding=encoding,
        )

    def enviar_evento(self, evento):
        return self._evento.enviar_evento(evento)

    def close(self):
        if self._closed:
            return
        self._closed = True

        first_error = None
        for service in (self._de, self._consulta, self._evento):
            try:
                service.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _cdcs_del_lote(lista_rde: list) -> tuple[str, ...]:
    """CDC (``DE.Id``) de cada binding del lote, en orden."""
    cdcs = (getattr(getattr(rde, "DE", None), "Id", None) for rde in lista_rde)
    return tuple(cdc for cdc in cdcs if cdc)
