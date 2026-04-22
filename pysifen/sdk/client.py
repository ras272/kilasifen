"""High-level SDK client facade for SIFEN operations."""
from __future__ import annotations

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
