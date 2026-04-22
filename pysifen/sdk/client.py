"""High-level SDK client facade for SIFEN operations."""
from __future__ import annotations

from pysifen.sdk.fiscal import (
    generate_cdc as _generate_cdc,
    generate_dcarqr as _generate_dcarqr,
)
from pysifen.sdk.polling import (
    PollingConfig,
    poll_dte_async_status,
    poll_lote_status,
)
from pysifen.transmissao import (
    ConsultaSIFEN,
    TransmissaoDE,
    TransmissaoEvento,
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
        base_kwargs = {
            "ambiente": ambiente,
            "pkcs12_data": pkcs12_data,
            "pkcs12_password": pkcs12_password,
            "timeout": timeout,
            "max_retries": max_retries,
            "retry_backoff": retry_backoff,
        }
        self._de = TransmissaoDE(**base_kwargs)
        self._consulta = ConsultaSIFEN(**base_kwargs)
        self._evento = TransmissaoEvento(**base_kwargs)
        self._closed = False

    def enviar_de(self, rde, sign: bool = True):
        return self._de.enviar_de(rde, sign=sign)

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

    def consultar_de(self, cdc: str):
        return self._consulta.consultar_de(cdc)

    def consultar_lote(self, prot_lote):
        return self._consulta.consultar_lote(prot_lote)

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
        """Dispara consulta async e espera resposta terminal com polling."""
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
    ):
        """Envia lote e bloqueia até estado terminal via polling."""
        envio = self.enviar_lote(
            lista_rde=lista_rde,
            lote_id=lote_id,
            sign=sign,
        )
        prot_lote = getattr(envio, "dProtConsLote", None)
        if prot_lote is None:
            raise ValueError(
                "enviar_lote response must include dProtConsLote"
            )
        return poll_lote_status(
            consultar_lote=self.consultar_lote,
            prot_lote=prot_lote,
            config=polling_config,
        )

    def generar_cdc(self, **kwargs):
        """Convenience wrapper around SDK fiscal CDC generator."""
        return _generate_cdc(**kwargs)

    def generar_dcarqr(self, **kwargs):
        """Convenience wrapper around SDK fiscal dCarQR generator."""
        return _generate_dcarqr(**kwargs)

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
