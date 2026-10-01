"""Consultas al SIFEN: documento por CDC, lote, RUC y DTE."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from xsdata.exceptions import ParserError

from kilasifen.engine.de.bindings.v150.ws_si_cons_de_v141 import (
    REnviConsDeRequest,
    REnviConsDeResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_dte import (
    RConsDteRequest,
    RConsDteResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_dteasync import (
    REnviConsDteAsyncRequest,
    REnviConsDteAsyncResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_lote_v141 import (
    REnviConsLoteDe,
    RResEnviConsLoteDe,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_ruc_v141 import (
    REnviConsRuc,
    RResEnviConsRuc,
)
from kilasifen.engine.transmision.base import TransmisionBase, _generate_id

__all__ = ["ConsultaSIFEN"]

#: Largo exacto de un CDC.
_LARGO_CDC = 44

#: Largo admitido del RUC a consultar, sin digito verificador.
_LARGO_MINIMO_RUC = 5
_LARGO_MAXIMO_RUC = 8


def _normalize_ruc(ruc: str) -> str:
    """Normaliza un RUC escrito por una persona.

    Recorta los blancos de los extremos, elimina los espacios internos y, si
    viene en la forma ``RUC-DV``, descarta el digito verificador. No verifica
    que el resultado sean digitos.

    Raises:
        ValueError: si hay un guion pero no exactamente dos partes no vacias.
    """
    texto = str(ruc).strip().replace(" ", "")
    if "-" not in texto:
        return texto
    partes = texto.split("-")
    if len(partes) != 2 or not all(partes):
        raise ValueError(f"RUC con formato no valido: {ruc!r}")
    return partes[0]


def _es_cdc_valido(cdc: str) -> bool:
    """Un CDC son exactamente 44 digitos ASCII (``0`` a ``9``).

    El largo se evalua primero; un valor sin ``len()`` lanza ``TypeError`` y
    uno que no es texto lanza ``AttributeError``.
    """
    return len(cdc) == _LARGO_CDC and cdc.isdigit() and cdc.isascii()


class ConsultaSIFEN(TransmisionBase):
    """Consultas de solo lectura a los web services del SIFEN.

    Como una consulta no tiene efecto fiscal, con ``max_retries > 0`` el
    transporte tambien reintenta los timeouts, los cortes de conexion y los
    errores 5xx, no solo los fallos en que la solicitud no salio.
    """

    _REINTENTA_ERRORES_AMBIGUOS = True

    def consultar_de(self, cdc: str) -> REnviConsDeResponse:
        """Consulta un DE por su CDC.

        Raises:
            ValueError: si el CDC no tiene exactamente 44 digitos.
        """
        if not _es_cdc_valido(cdc):
            raise ValueError(
                f"El CDC debe tener exactamente {_LARGO_CDC} digitos numericos; "
                f"se recibio {cdc!r} ({len(cdc)} caracteres)"
            )
        solicitud = REnviConsDeRequest(dId=_generate_id(), dCDC=cdc)
        respuesta = self._get_client("cons_de").send(solicitud)
        return self._como_respuesta(respuesta, REnviConsDeResponse)

    def consultar_lote(self, prot_lote: int | Decimal | str) -> RResEnviConsLoteDe:
        """Consulta el estado de un lote por su numero de protocolo.

        Raises:
            decimal.InvalidOperation: si ``prot_lote`` no es numerico.
        """
        solicitud = REnviConsLoteDe(
            dId=_generate_id(),
            dProtConsLote=Decimal(str(prot_lote)),
        )
        respuesta = self._get_client("cons_lote").send(solicitud)
        return self._como_respuesta(respuesta, RResEnviConsLoteDe)

    def consultar_ruc(self, ruc: str) -> RResEnviConsRuc:
        """Consulta los datos de un contribuyente por RUC.

        Acepta formatos humanos (con espacios o como ``RUC-DV``). Si el SIFEN
        responde con un sobre que no corresponde a esta consulta, se reabre la
        conexion y se reintenta con el mismo request (ver
        :meth:`~kilasifen.engine.transmision.base.TransmisionBase._send_safe_query`).

        Raises:
            ValueError: si el RUC esta mal formado o, sin el digito
                verificador, no tiene de 5 a 8 caracteres.
        """
        ruc_normalizado = _normalize_ruc(ruc)
        largo = len(ruc_normalizado)
        if not _LARGO_MINIMO_RUC <= largo <= _LARGO_MAXIMO_RUC:
            raise ValueError(
                f"El RUC a consultar debe tener de {_LARGO_MINIMO_RUC} a "
                f"{_LARGO_MAXIMO_RUC} caracteres; se recibio "
                f"{ruc_normalizado!r} ({largo} caracteres)"
            )

        solicitud = REnviConsRuc(dId=_generate_id(), dRUCCons=ruc_normalizado)
        cliente = self._get_client("cons_ruc")
        try:
            respuesta = cliente.send(solicitud)
        except ParserError:
            self._cleanup_transport()
            return self._send_safe_query("cons_ruc", solicitud, RResEnviConsRuc)
        return self._como_respuesta(respuesta, RResEnviConsRuc)

    def consultar_dte(self, consulta_dte: Any) -> RConsDteResponse:
        """Consulta un DTE con el ``rConsultaDTE`` recibido."""
        solicitud = RConsDteRequest(rConsultaDTE=consulta_dte)
        respuesta = self._get_client("cons_dte").send(solicitud)
        return self._como_respuesta(respuesta, RConsDteResponse)

    def consultar_dte_async(
        self,
        consulta_dte_async: Any,
    ) -> REnviConsDteAsyncResponse:
        """Registra una consulta DTE asincrona y devuelve su protocolo."""
        solicitud = REnviConsDteAsyncRequest(rConsultaDTE=consulta_dte_async)
        respuesta = self._get_client("cons_dte_async").send(solicitud)
        return self._como_respuesta(respuesta, REnviConsDteAsyncResponse)
