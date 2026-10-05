"""Espera del resultado de un lote y de la consulta DTE asincronica.

La consulta de lote sigue el MT v150 (Tabla F, p. 49; sec. 12.3.3, pp.
155-156) y la Guia de mejores practicas para la gestion del envio de DE
(DNIT, oct-2024, pp. 6, 9 y 10):

* solo se consulta un lote recibido con ``0300`` y numero de lote
  (``dProtConsLote``); con ``0301`` el lote no se procesa;
* ``0361`` (lote en procesamiento) es el unico codigo pendiente;
* ``0362`` (procesamiento concluido) es terminal y trae en ``gResProcLote``
  el resultado de cada DE;
* ``0360``, ``0363``, ``0340`` y ``0320`` son errores;
* ``0364`` (consulta extemporanea) o mas de 48 h desde la recepcion obligan a
  consultar cada CDC con siConsDE.

La primera consulta va pasados 10 minutos de la recepcion y las siguientes a
intervalos de al menos 10 minutos; el procesamiento puede tardar de 1 a 24 h.
Para esperas tan largas conviene programar cada consulta como un job con
:func:`classify_lote_response` y :func:`lote_document_results`, en lugar de
bloquear un proceso con :func:`poll_lote_status`.

La consulta DTE (sincronica y asincronica) es EXPERIMENTAL: la SET publica
sus XSD, pero ni el MT v150 ni las NT 01-27 ni la Guia documentan su
direccion, sus codigos de resultado, sus mensajes de pendiente ni sus plazos
(NO DETERMINADO). :func:`poll_dte_async_status` no supone ningun texto de
"pendiente".
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from kilasifen.engine.sdk.errors import (
    SifenLoteError,
    SifenRejectionError,
    SifenTimeoutError,
)

__all__ = [
    "CONSULTA_DE_FOUND_CODE",
    "CONSULTA_DE_NOT_FOUND_CODE",
    "LOTE_CONCLUDED_CODE",
    "LOTE_ERROR_CODES",
    "LOTE_EXPIRED_CODE",
    "LOTE_MIN_INTERVAL_SECONDS",
    "LOTE_PENDING_CODE",
    "LOTE_QUERY_WINDOW_SECONDS",
    "LOTE_RECEIVED_CODE",
    "LoteDocumentResult",
    "LoteResult",
    "PollingConfig",
    "classify_lote_response",
    "consulta_de_result",
    "lote_document_results",
    "poll_dte_async_status",
    "poll_lote_status",
    "require_lote_protocol",
]

#: Recepcion del lote exitosa: el lote se procesara (MT sec. 12.3.2.3, p. 155).
LOTE_RECEIVED_CODE = "0300"

#: Unico codigo pendiente: "Lote en procesamiento". El MT (sec. 12.3.3.3, p.
#: 156) lo marca R, pero la Tabla F (p. 49) y la Guia (p. 10) piden volver a
#: consultar.
LOTE_PENDING_CODE = "0361"

#: "Procesamiento de lote concluido": terminal, con ``gResProcLote`` por DE.
LOTE_CONCLUDED_CODE = "0362"

#: "Consulta extemporanea de Lote": pasadas 48 h hay que consultar cada CDC
#: con siConsDE (Guia, p. 10).
LOTE_EXPIRED_CODE = "0364"

#: Errores de la consulta de lote (MT Tabla F, p. 49; sec. 12.3.3, pp.
#: 155-156).
LOTE_ERROR_CODES: Mapping[str, str] = MappingProxyType(
    {
        "0320": "mensaje de consulta mayor a 1000 KB",
        "0340": "RUC del certificado no autorizado a consultar el lote",
        "0360": "numero de lote inexistente",
        "0363": "lote con tipos distintos de DE",
    }
)

#: Plazo para consultar un lote desde su recepcion (Guia, p. 10).
LOTE_QUERY_WINDOW_SECONDS = 48 * 3600

#: Espera minima recomendada antes de la primera consulta y entre consultas
#: (Guia, p. 6, punto 4; p. 9; p. 10).
LOTE_MIN_INTERVAL_SECONDS = 600

#: siConsDE: el CDC existe como DTE aprobado y trae ``xContenDE``.
CONSULTA_DE_FOUND_CODE = "0422"

#: siConsDE: el DE no existe en el SIFEN o fue rechazado (Guia, p. 12).
CONSULTA_DE_NOT_FOUND_CODE = "0420"

_STATUS_PENDING = "pending"
_STATUS_CONCLUDED = "concluded"
_STATUS_EXPIRED = "expired"


@dataclass(frozen=True)
class PollingConfig:
    """Ritmo de las consultas repetidas.

    Los valores por defecto siguen la Guia de mejores practicas para el lote:
    primera consulta a los 600 s, intervalos de 600 s y un tope de 48 h.
    Se pueden achicar (por ejemplo, en pruebas), pero contra el SIFEN no se
    recomiendan intervalos menores a 600 s.

    Attributes:
        interval_seconds: espera entre una consulta pendiente y la siguiente.
        timeout_seconds: tiempo maximo de espera de esta llamada, contado
            desde que empieza; vencido, se lanza :class:`SifenTimeoutError`.
        max_attempts: cantidad maxima de respuestas pendientes antes de
            lanzar :class:`SifenTimeoutError` (``None``: sin tope).
        initial_delay_seconds: espera antes de la primera consulta, contada
            desde la recepcion.
    """

    interval_seconds: float = float(LOTE_MIN_INTERVAL_SECONDS)
    timeout_seconds: float = float(LOTE_QUERY_WINDOW_SECONDS)
    max_attempts: None | int = None
    initial_delay_seconds: float = float(LOTE_MIN_INTERVAL_SECONDS)

    def __post_init__(self) -> None:
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.max_attempts is not None and self.max_attempts <= 0:
            raise ValueError("max_attempts must be > 0")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be >= 0")


@dataclass(frozen=True)
class LoteDocumentResult:
    """Resultado de un DE del lote.

    Attributes:
        cdc: CDC del documento.
        status: con ``source == "consulta_lote"``, el ``dEstRes`` normalizado:
            ``"approved"``, ``"approved_with_observation"``, ``"rejected"``
            o ``"unknown"`` si no es ninguno de los tres. Con
            ``source == "consulta_de"``: ``"found"`` (0422, DTE aprobado),
            ``"not_found_or_not_approved"`` (0420) o ``"error"`` (cualquier
            otro codigo).
        source: ``"consulta_lote"`` (``gResProcLote`` de un 0362) o
            ``"consulta_de"`` (siConsDE tras 0364 o 48 h).
        messages: pares ``(dCodRes, dMsgRes)`` informados para el DE.
        protocol: ``dProtAut`` del lote, si vino.
        response: el ``gResProcLote`` o la respuesta de siConsDE originales.
    """

    cdc: str
    status: str
    source: str
    messages: tuple[tuple[str, str], ...]
    protocol: str | None
    response: Any


@dataclass(frozen=True)
class LoteResult:
    """Resultado final de la espera de un lote.

    Attributes:
        status: ``"concluded"`` (0362) o ``"expired"`` (0364 o mas de 48 h
            desde la recepcion; el detalle sale de siConsDE).
        response: ultima respuesta de la consulta de lote (``None`` si el
            plazo ya habia vencido antes de consultar).
        documents: resultado de cada DE.
    """

    status: str
    response: Any
    documents: tuple[LoteDocumentResult, ...]


def require_lote_protocol(reception: Any) -> Any:
    """Devuelve el ``dProtConsLote`` de una recepcion de lote ``0300``.

    Solo un lote recibido con ``0300`` se consulta, y solo esa respuesta
    trae el numero de lote (MT sec. 9.2.3, p. 48, y sec. 12.3.2.3, p. 155;
    Guia, p. 9).

    Raises:
        SifenRejectionError: si ``dCodRes`` no es ``0300`` (por ejemplo,
            ``0301``, lote no encolado): no hay nada que consultar.
        SifenLoteError: si la recepcion es ``0300`` pero no trae
            ``dProtConsLote``; el lote se puede consultar con un CDC
            (``consultar_lote(cdc=...)``).
    """
    code = _text(getattr(reception, "dCodRes", None))
    message = _text(getattr(reception, "dMsgRes", None))
    if code != LOTE_RECEIVED_CODE:
        raise SifenRejectionError(
            code,
            f"El lote no fue encolado ({code or 'sin codigo'}): {message}; "
            "no se consulta",
        )
    protocol = getattr(reception, "dProtConsLote", None)
    if protocol is None or _text(protocol) == "":
        raise SifenLoteError(
            code,
            "La recepcion del lote fue 0300 pero no trae dProtConsLote; "
            "consultar el lote con uno de sus CDC (consultar_lote(cdc=...))",
            reception,
        )
    return protocol


def classify_lote_response(response: Any) -> str:
    """Clasifica una respuesta de consulta de lote por su ``dCodResLot``.

    Returns:
        ``"pending"`` (0361), ``"concluded"`` (0362) o ``"expired"`` (0364).

    Raises:
        SifenLoteError: con 0360, 0363, 0340 o 0320, o con un codigo
            ausente o no documentado.
    """
    code = _text(getattr(response, "dCodResLot", None))
    if code == LOTE_PENDING_CODE:
        return _STATUS_PENDING
    if code == LOTE_CONCLUDED_CODE:
        return _STATUS_CONCLUDED
    if code == LOTE_EXPIRED_CODE:
        return _STATUS_EXPIRED
    message = _text(getattr(response, "dMsgResLot", None))
    if code in LOTE_ERROR_CODES:
        raise SifenLoteError(
            code,
            f"La consulta del lote fallo con {code} "
            f"({LOTE_ERROR_CODES[code]}): {message}",
            response,
        )
    raise SifenLoteError(
        code or None,
        f"Codigo de consulta de lote no documentado: {code!r} {message}".rstrip(),
        response,
    )


def lote_document_results(response: Any) -> tuple[LoteDocumentResult, ...]:
    """Resultado de cada DE de una consulta de lote ``0362``.

    Lee ``gResProcLote`` (``id``, ``dEstRes``, ``dProtAut`` y hasta 5
    ``gResProc``; XSD ``WS_SiConsLote_v141.xsd``). ``dEstRes`` se compara
    sin tildes ni mayusculas, porque el texto varia entre el MT y la Guia.
    """
    return tuple(
        LoteDocumentResult(
            cdc=_text(getattr(detalle, "id", None)),
            status=_lote_document_status(getattr(detalle, "dEstRes", None)),
            source="consulta_lote",
            messages=_messages(getattr(detalle, "gResProc", None) or ()),
            protocol=_optional_text(getattr(detalle, "dProtAut", None)),
            response=detalle,
        )
        for detalle in getattr(response, "gResProcLote", None) or ()
    )


def consulta_de_result(cdc: str, response: Any) -> LoteDocumentResult:
    """Resultado de un DE consultado con siConsDE.

    ``0422``: existe como DTE aprobado; ``0420``: no existe o fue rechazado;
    cualquier otro codigo es un error de la consulta (MT Tabla G, p. 51;
    Guia, p. 12).
    """
    code = _text(getattr(response, "dCodRes", None))
    if code == CONSULTA_DE_FOUND_CODE:
        status = "found"
    elif code == CONSULTA_DE_NOT_FOUND_CODE:
        status = "not_found_or_not_approved"
    else:
        status = "error"
    return LoteDocumentResult(
        cdc=cdc,
        status=status,
        source="consulta_de",
        messages=((code, _text(getattr(response, "dMsgRes", None))),),
        protocol=None,
        response=response,
    )


def poll_lote_status(
    consultar_lote: Callable[[Any], Any],
    prot_lote: Any,
    config: PollingConfig = PollingConfig(),
    *,
    cdcs: Sequence[str] = (),
    consultar_de: Callable[[str], Any] | None = None,
    seconds_since_reception: float = 0.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> LoteResult:
    """Consulta un lote hasta que concluye, bloqueando el proceso.

    Espera ``config.initial_delay_seconds`` desde la recepcion, consulta con
    ``consultar_lote(prot_lote)`` y repite cada ``config.interval_seconds``
    mientras la respuesta sea ``0361``. Con ``0364``, o si pasan 48 h desde
    la recepcion, consulta cada CDC de ``cdcs`` con ``consultar_de``.

    Args:
        consultar_lote: funcion que hace una consulta de lote.
        prot_lote: numero de lote (``dProtConsLote``) de la recepcion 0300.
        config: ritmo de las consultas.
        cdcs: CDC del lote, para pasar a siConsDE.
        consultar_de: funcion de siConsDE (``ConsultaSIFEN.consultar_de``).
        seconds_since_reception: segundos que ya pasaron desde la recepcion
            del lote, cuando la espera se retoma mas tarde.
        clock: reloj monotono, en segundos.
        sleep: funcion de espera, en segundos.

    Returns:
        Un :class:`LoteResult` ``"concluded"`` (0362) o ``"expired"``.

    Raises:
        SifenLoteError: si la consulta devuelve un error o un codigo no
            documentado, o si vence el plazo sin ``cdcs`` o sin
            ``consultar_de``.
        SifenTimeoutError: si el lote sigue en procesamiento al agotarse
            ``config.timeout_seconds`` o ``config.max_attempts``.
    """
    started_at = clock()

    def since_reception() -> float:
        return seconds_since_reception + (clock() - started_at)

    initial_wait = config.initial_delay_seconds - seconds_since_reception
    if initial_wait > 0:
        sleep(initial_wait)

    attempts = 0
    response = None
    while since_reception() < LOTE_QUERY_WINDOW_SECONDS:
        response = consultar_lote(prot_lote)
        status = classify_lote_response(response)
        if status == _STATUS_CONCLUDED:
            return LoteResult(
                status=_STATUS_CONCLUDED,
                response=response,
                documents=lote_document_results(response),
            )
        if status == _STATUS_EXPIRED:
            break
        attempts += 1
        if config.max_attempts is not None and attempts >= config.max_attempts:
            raise SifenTimeoutError("Polling timeout while waiting lote status.")
        if clock() - started_at >= config.timeout_seconds:
            raise SifenTimeoutError("Polling timeout while waiting lote status.")
        if config.interval_seconds > 0:
            sleep(config.interval_seconds)
    return _expired_lote_result(cdcs, consultar_de, response)


def poll_dte_async_status(
    fetch_status: Callable[[str], Any],
    protocol_id: str,
    config: PollingConfig = PollingConfig(),
    pending_tokens: tuple[str, ...] = (),
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Consulta el resultado de una consulta DTE asincronica (EXPERIMENTAL).

    El servicio no esta documentado por la SET (ver el docstring del
    modulo): no hay mensajes de "pendiente" oficiales. Devuelve la primera
    respuesta que trae ``rConsDte`` o cuyo ``dMsgRes`` no contiene ninguno
    de los ``pending_tokens`` que indique quien llama; sin tokens, devuelve
    la primera respuesta. Espera ``config.initial_delay_seconds`` antes de la
    primera consulta, como con el lote.

    Raises:
        SifenTimeoutError: si se agotan ``config.timeout_seconds`` o
            ``config.max_attempts`` con respuestas pendientes.
    """
    started_at = clock()
    if config.initial_delay_seconds > 0:
        sleep(config.initial_delay_seconds)
    tokens = tuple(token.upper() for token in pending_tokens)
    attempts = 0

    while True:
        response = fetch_status(protocol_id)
        if getattr(response, "rConsDte", None):
            return response

        message = _text(getattr(response, "dMsgRes", None)).upper()
        if not message or not any(token in message for token in tokens):
            return response

        attempts += 1
        if config.max_attempts is not None and attempts >= config.max_attempts:
            raise SifenTimeoutError("Polling timeout while waiting DTE async result.")
        if clock() - started_at >= config.timeout_seconds:
            raise SifenTimeoutError("Polling timeout while waiting DTE async result.")
        if config.interval_seconds > 0:
            sleep(config.interval_seconds)


def _expired_lote_result(
    cdcs: Sequence[str],
    consultar_de: Callable[[str], Any] | None,
    response: Any,
) -> LoteResult:
    """Pasa a siConsDE por cada CDC cuando la consulta del lote ya no sirve.

    Raises:
        SifenLoteError: si no se indicaron los CDC o la funcion de siConsDE.
    """
    if consultar_de is None or not cdcs:
        raise SifenLoteError(
            _optional_text(getattr(response, "dCodResLot", None)),
            "La consulta del lote ya no esta disponible (0364 o mas de 48 h "
            "desde la recepcion): consultar cada CDC del lote con siConsDE",
            response,
        )
    return LoteResult(
        status=_STATUS_EXPIRED,
        response=response,
        documents=tuple(consulta_de_result(cdc, consultar_de(cdc)) for cdc in cdcs),
    )


def _lote_document_status(estado: Any) -> str:
    """Normaliza ``dEstRes`` de ``gResProcLote`` (MT sec. 9.3.2, p. 49)."""
    texto = _normalize(_text(estado))
    if texto.startswith("aprobado con observ"):
        return "approved_with_observation"
    if texto.startswith("aprobado"):
        return "approved"
    if texto.startswith("rechazado"):
        return "rejected"
    return "unknown"


def _messages(resultados: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        (_text(getattr(item, "dCodRes", None)), _text(getattr(item, "dMsgRes", None)))
        for item in resultados
    )


def _normalize(texto: str) -> str:
    """Minusculas, sin tildes y con los blancos colapsados."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def _text(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _optional_text(valor: Any) -> str | None:
    texto = _text(valor)
    return texto or None
