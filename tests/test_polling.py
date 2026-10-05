"""Pruebas de la espera de lotes (F66) y de la consulta DTE asincronica.

Codigos y plazos: MT v150 Tabla F (p. 49) y sec. 12.3.3 (pp. 155-156); Guia
de mejores practicas para la gestion del envio de DE (DNIT, oct-2024), pp. 6,
9, 10 y 12. Los CDC y RUC son ficticios (``tests/_muestras.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from kilasifen.engine.de.bindings.v150.prot_proces_eventos_v141 import TgResProc
from kilasifen.engine.de.bindings.v150.ws_si_cons_de_v141 import REnviConsDeResponse
from kilasifen.engine.de.bindings.v150.ws_si_cons_lote_v141 import (
    RResEnviConsLoteDe,
    TgResProcLote,
)
from kilasifen.engine.de.bindings.v150.ws_si_recep_lote_de_v141 import (
    RResEnviLoteDe,
)
from kilasifen.engine.sdk.errors import (
    SifenLoteError,
    SifenRejectionError,
    SifenTimeoutError,
)
from kilasifen.engine.sdk.polling import (
    LOTE_ERROR_CODES,
    LOTE_MIN_INTERVAL_SECONDS,
    LOTE_QUERY_WINDOW_SECONDS,
    PollingConfig,
    classify_lote_response,
    consulta_de_result,
    lote_document_results,
    poll_dte_async_status,
    poll_lote_status,
    require_lote_protocol,
)
from tests._muestras import AUTOFACTURA, FACTURA, NOTA_CREDITO

FECHA_PROCESO = "2026-03-14T09:26:53-03:00"
PROTOCOLO = Decimal("11158097383597290")
CDCS = (FACTURA.cdc, NOTA_CREDITO.cdc, AUTOFACTURA.cdc)
HORA = 3600


class Reloj:
    """Reloj monotono y ``sleep`` simulados: dormir adelanta el reloj."""

    def __init__(self) -> None:
        self.ahora = 0.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.ahora

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.ahora += segundos


class ConsultasDeLote:
    """``consultar_lote`` simulado: entrega las respuestas en orden."""

    def __init__(self, *respuestas: Any) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[Any] = []

    def __call__(self, prot_lote: Any) -> Any:
        self.llamadas.append(prot_lote)
        if len(self._respuestas) > 1:
            return self._respuestas.pop(0)
        return self._respuestas[0]


def _lote(codigo: str, mensaje: str = "Mensaje", detalle: Any = ()) -> Any:
    return RResEnviConsLoteDe(
        dFecProc=FECHA_PROCESO,
        dCodResLot=codigo,
        dMsgResLot=mensaje,
        gResProcLote=list(detalle),
    )


def _consulta_de(codigo: str, mensaje: str) -> REnviConsDeResponse:
    return REnviConsDeResponse(
        dFecProc=FECHA_PROCESO, dCodRes=codigo, dMsgRes=mensaje
    )


def _esperar(
    consultar_lote: Any, reloj: Reloj, config: PollingConfig = PollingConfig(), **kw
) -> Any:
    return poll_lote_status(
        consultar_lote,
        PROTOCOLO,
        config,
        clock=reloj,
        sleep=reloj.dormir,
        **kw,
    )


# ---------------------------------------------------------------------------
# Ritmo y codigos de la consulta de lote
# ---------------------------------------------------------------------------


def test_valores_por_defecto_de_la_guia():
    """Guia p. 6 punto 4 y p. 10: 10 minutos de espera y 48 h de plazo."""
    config = PollingConfig()
    assert LOTE_MIN_INTERVAL_SECONDS == 600
    assert LOTE_QUERY_WINDOW_SECONDS == 48 * HORA
    assert config.initial_delay_seconds == 600
    assert config.interval_seconds == 600
    assert config.timeout_seconds == 48 * HORA
    assert config.max_attempts is None


def test_solo_0361_es_pendiente_y_0362_concluye():
    reloj = Reloj()
    consultas = ConsultasDeLote(_lote("0361"), _lote("0361"), _lote("0362"))

    resultado = _esperar(consultas, reloj)

    assert resultado.status == "concluded"
    assert resultado.response.dCodResLot == "0362"
    assert consultas.llamadas == [PROTOCOLO] * 3
    # Primera consulta a los 600 s de la recepcion; despues cada 600 s.
    assert reloj.esperas == [600, 600, 600]


@pytest.mark.parametrize("codigo", ["0300", "0301", "9999", "", None])
def test_codigo_no_documentado_no_es_pendiente(codigo: str | None):
    """Antes ``0300`` contaba como pendiente, pero nunca es un ``dCodResLot``."""
    reloj = Reloj()
    consultas = ConsultasDeLote(SimpleNamespace(dCodResLot=codigo, dMsgResLot="X"))

    with pytest.raises(SifenLoteError, match="no documentado"):
        _esperar(consultas, reloj)

    assert len(consultas.llamadas) == 1


@pytest.mark.parametrize("codigo", sorted(LOTE_ERROR_CODES))
def test_codigos_de_error_de_la_consulta(codigo: str):
    """0360, 0363, 0340 y 0320 son errores (MT Tabla F y sec. 12.3.3)."""
    reloj = Reloj()
    respuesta = _lote(codigo, mensaje="Detalle del SIFEN")
    consultas = ConsultasDeLote(respuesta)

    with pytest.raises(SifenLoteError) as error:
        _esperar(consultas, reloj)

    assert error.value.code == codigo
    assert error.value.response is respuesta
    assert "Detalle del SIFEN" in str(error.value)
    assert len(consultas.llamadas) == 1


def test_0360_no_se_reintenta():
    """0360 ("lote inexistente") era pendiente; ahora es error."""
    assert set(LOTE_ERROR_CODES) == {"0320", "0340", "0360", "0363"}
    with pytest.raises(SifenLoteError):
        classify_lote_response(_lote("0360"))


@pytest.mark.parametrize(
    "codigo, estado",
    [("0361", "pending"), ("0362", "concluded"), ("0364", "expired")],
)
def test_clasificacion_de_la_respuesta(codigo: str, estado: str):
    assert classify_lote_response(_lote(codigo)) == estado


# ---------------------------------------------------------------------------
# Detalle por DE (0362)
# ---------------------------------------------------------------------------


def test_0362_trae_el_detalle_de_cada_de():
    rechazo = TgResProc(dCodRes="0160", dMsgRes="XML malformado")
    observacion = TgResProc(dCodRes="1005", dMsgRes="Transmision extemporanea")
    detalle = [
        TgResProcLote(
            id=FACTURA.cdc,
            dEstRes="Aprobado",
            dProtAut="4401920517",
            gResProc=[TgResProc(dCodRes="0260", dMsgRes="Autorizado")],
        ),
        TgResProcLote(
            id=NOTA_CREDITO.cdc,
            dEstRes="Aprobado con Observación",
            dProtAut="4401920518",
            gResProc=[observacion],
        ),
        TgResProcLote(id=AUTOFACTURA.cdc, dEstRes="Rechazado", gResProc=[rechazo]),
    ]
    reloj = Reloj()

    resultado = _esperar(ConsultasDeLote(_lote("0362", detalle=detalle)), reloj)

    documentos = resultado.documents
    assert [d.cdc for d in documentos] == list(CDCS)
    assert [d.status for d in documentos] == [
        "approved",
        "approved_with_observation",
        "rejected",
    ]
    assert {d.source for d in documentos} == {"consulta_lote"}
    assert documentos[0].protocol == "4401920517"
    assert documentos[1].messages == (("1005", "Transmision extemporanea"),)
    assert documentos[2].protocol is None
    assert documentos[2].messages == (("0160", "XML malformado"),)
    assert documentos[2].response is detalle[2]


@pytest.mark.parametrize(
    "texto, estado",
    [
        ("Aprobado", "approved"),
        ("APROBADO", "approved"),
        ("Aprobado con observación", "approved_with_observation"),
        ("APROBADO CON OBSERVACIONES", "approved_with_observation"),
        ("Rechazado", "rejected"),
        ("En revision", "unknown"),
    ],
)
def test_destres_se_compara_normalizado(texto: str, estado: str):
    """El literal varia entre el MT (sec. 9 y cap. 12) y la Guia."""
    detalle = [TgResProcLote(id=FACTURA.cdc, dEstRes=texto)]
    (documento,) = lote_document_results(_lote("0362", detalle=detalle))
    assert documento.status == estado


# ---------------------------------------------------------------------------
# 0364 o mas de 48 h: siConsDE por CDC
# ---------------------------------------------------------------------------


def _consultar_de_simulado(llamadas: list[str]) -> Any:
    respuestas = {
        FACTURA.cdc: _consulta_de("0422", "CDC encontrado"),
        NOTA_CREDITO.cdc: _consulta_de(
            "0420", "Documento No Existe en SIFEN o ha sido Rechazado"
        ),
        AUTOFACTURA.cdc: _consulta_de("0421", "Otro resultado"),
    }

    def consultar_de(cdc: str) -> Any:
        llamadas.append(cdc)
        return respuestas[cdc]

    return consultar_de


def test_0364_pasa_a_consulta_de_por_cada_cdc():
    """Guia p. 10: consulta extemporanea, consultar cada CDC (siConsDE)."""
    reloj = Reloj()
    extemporanea = _lote("0364", mensaje="Consulta extemporanea de Lote")
    llamadas: list[str] = []

    resultado = _esperar(
        ConsultasDeLote(_lote("0361"), extemporanea),
        reloj,
        cdcs=CDCS,
        consultar_de=_consultar_de_simulado(llamadas),
    )

    assert resultado.status == "expired"
    assert resultado.response is extemporanea
    assert llamadas == list(CDCS)
    assert [d.status for d in resultado.documents] == [
        "found",
        "not_found_or_not_approved",
        "error",
    ]
    assert {d.source for d in resultado.documents} == {"consulta_de"}
    assert resultado.documents[1].messages == (
        ("0420", "Documento No Existe en SIFEN o ha sido Rechazado"),
    )


def test_0364_sin_consulta_de_es_error():
    reloj = Reloj()
    with pytest.raises(SifenLoteError, match="siConsDE") as error:
        _esperar(ConsultasDeLote(_lote("0364")), reloj, cdcs=CDCS)
    assert error.value.code == "0364"


def test_pasadas_48_horas_deja_de_consultar_el_lote():
    """El plazo se cuenta desde la recepcion, aunque la espera se retome."""
    reloj = Reloj()
    consultas = ConsultasDeLote(_lote("0361"))
    llamadas: list[str] = []

    resultado = _esperar(
        consultas,
        reloj,
        cdcs=CDCS[:1],
        consultar_de=_consultar_de_simulado(llamadas),
        seconds_since_reception=48 * HORA - 900,
    )

    # Consultas a las 47 h 45 min y a las 47 h 55 min; la siguiente caeria
    # despues de las 48 h.
    assert len(consultas.llamadas) == 2
    assert reloj.esperas == [600, 600]
    assert resultado.status == "expired"
    assert resultado.response.dCodResLot == "0361"
    assert llamadas == [FACTURA.cdc]


def test_vencido_antes_de_empezar_no_consulta_el_lote():
    reloj = Reloj()
    consultas = ConsultasDeLote(_lote("0361"))
    llamadas: list[str] = []

    resultado = _esperar(
        consultas,
        reloj,
        cdcs=CDCS[:1],
        consultar_de=_consultar_de_simulado(llamadas),
        seconds_since_reception=48 * HORA,
    )

    assert consultas.llamadas == []
    assert reloj.esperas == []
    assert resultado.response is None
    assert llamadas == [FACTURA.cdc]


def test_espera_retomada_descuenta_lo_transcurrido():
    reloj = Reloj()
    _esperar(ConsultasDeLote(_lote("0362")), reloj, seconds_since_reception=420)
    assert reloj.esperas == [180]


# ---------------------------------------------------------------------------
# Tope de espera de la llamada
# ---------------------------------------------------------------------------


def test_max_attempts_con_el_lote_en_procesamiento():
    reloj = Reloj()
    consultas = ConsultasDeLote(_lote("0361"))

    with pytest.raises(SifenTimeoutError):
        _esperar(consultas, reloj, PollingConfig(max_attempts=3))

    assert len(consultas.llamadas) == 3


def test_timeout_con_el_lote_en_procesamiento():
    reloj = Reloj()
    consultas = ConsultasDeLote(_lote("0361"))
    config = PollingConfig(timeout_seconds=2 * HORA)

    with pytest.raises(SifenTimeoutError):
        _esperar(consultas, reloj, config)

    # Consultas a los 600, 1200, ..., 7200 s: la ultima agota las 2 h.
    assert len(consultas.llamadas) == 12
    assert reloj.ahora == 2 * HORA


def test_config_rechaza_valores_negativos():
    with pytest.raises(ValueError, match="initial_delay_seconds"):
        PollingConfig(initial_delay_seconds=-1)
    with pytest.raises(ValueError, match="interval_seconds"):
        PollingConfig(interval_seconds=-1)
    with pytest.raises(ValueError, match="timeout_seconds"):
        PollingConfig(timeout_seconds=0)
    with pytest.raises(ValueError, match="max_attempts"):
        PollingConfig(max_attempts=0)


# ---------------------------------------------------------------------------
# Recepcion: solo se consulta con 0300 y numero de lote
# ---------------------------------------------------------------------------


def test_recepcion_0300_entrega_el_numero_de_lote():
    recepcion = RResEnviLoteDe(
        dFecProc=FECHA_PROCESO,
        dCodRes="0300",
        dMsgRes="Lote recibido con éxito",
        dProtConsLote=PROTOCOLO,
        dTpoProces=0,
    )
    assert require_lote_protocol(recepcion) == PROTOCOLO


def test_recepcion_0301_no_se_consulta():
    recepcion = RResEnviLoteDe(
        dCodRes="0301", dMsgRes="Lote no encolado para procesamiento"
    )
    with pytest.raises(SifenRejectionError) as error:
        require_lote_protocol(recepcion)
    assert error.value.code == "0301"
    assert "no encolado" in str(error.value)


def test_recepcion_0300_sin_numero_de_lote():
    recepcion = RResEnviLoteDe(dCodRes="0300", dMsgRes="Lote recibido")
    with pytest.raises(SifenLoteError, match="dProtConsLote") as error:
        require_lote_protocol(recepcion)
    assert error.value.code == "0300"
    assert error.value.response is recepcion


def test_consulta_de_result_clasifica_por_codigo():
    assert consulta_de_result(FACTURA.cdc, _consulta_de("0422", "Ok")).status == (
        "found"
    )
    assert consulta_de_result(FACTURA.cdc, _consulta_de("0420", "No")).status == (
        "not_found_or_not_approved"
    )
    assert consulta_de_result(FACTURA.cdc, _consulta_de("0160", "XML")).status == (
        "error"
    )


# ---------------------------------------------------------------------------
# Consulta DTE asincronica (experimental, sin textos de pendiente oficiales)
# ---------------------------------------------------------------------------


@dataclass
class DteResponse:
    dMsgRes: str
    rConsDte: bytes | None = None


def _esperar_dte(fetch: Any, reloj: Reloj, **kw: Any) -> Any:
    return poll_dte_async_status(
        fetch, "ABC123", clock=reloj, sleep=reloj.dormir, **kw
    )


def test_dte_sin_tokens_no_supone_un_pendiente():
    """No hay mensajes de "pendiente" documentados: no se inventan."""
    llamadas: list[str] = []

    def fetch_status(protocolo: str) -> DteResponse:
        llamadas.append(protocolo)
        return DteResponse(dMsgRes="Pendiente de procesamiento")

    resultado = _esperar_dte(fetch_status, Reloj())

    assert resultado.dMsgRes == "Pendiente de procesamiento"
    assert llamadas == ["ABC123"]


def test_dte_con_tokens_explicitos_espera_el_archivo():
    respuestas = [
        DteResponse(dMsgRes="Pendiente de procesamiento"),
        DteResponse(dMsgRes="Disponible", rConsDte=b"zip-data"),
    ]
    reloj = Reloj()

    resultado = _esperar_dte(
        lambda _protocolo: respuestas.pop(0),
        reloj,
        config=PollingConfig(initial_delay_seconds=0, interval_seconds=5),
        pending_tokens=("pendiente",),
    )

    assert resultado.rConsDte == b"zip-data"
    assert reloj.esperas == [5]


def test_dte_se_detiene_ante_un_mensaje_no_pendiente():
    resultado = _esperar_dte(
        lambda _protocolo: DteResponse(dMsgRes="Error de consulta"),
        Reloj(),
        pending_tokens=("PENDIENTE",),
    )
    assert resultado.dMsgRes == "Error de consulta"
    assert resultado.rConsDte is None


def test_dte_timeout_con_tokens_explicitos():
    reloj = Reloj()
    with pytest.raises(SifenTimeoutError):
        _esperar_dte(
            lambda _protocolo: DteResponse(dMsgRes="En proceso"),
            reloj,
            config=PollingConfig(max_attempts=2),
            pending_tokens=("EN PROCESO",),
        )
    assert reloj.esperas == [600, 600]
