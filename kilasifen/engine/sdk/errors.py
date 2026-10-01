"""Errores tipados del SDK de KilaSifen."""

from __future__ import annotations

#: Caracteres del cuerpo recibido que conserva :class:`SifenUnexpectedResponseError`.
MAX_CUERPO_CRUDO = 4096


class SifenError(Exception):
    """Error base del SDK."""


class SifenValidationError(SifenError):
    """Error de validacion de entrada o contrato."""


class SifenSignatureError(SifenError):
    """Error al firmar XML o preparar la firma."""


class SifenTransportError(SifenError):
    """Error al transportar mensajes SOAP.

    Salvo que sea una :class:`SifenRequestNotSentError` o una
    :class:`SifenTransportClosedError` (ambas se lanzan antes de enviar), el
    SIFEN pudo haber recibido y procesado la solicitud: el resultado de un
    envio con efecto fiscal queda incierto y hay que consultarlo antes de
    volver a enviar.
    """


class SifenRequestNotSentError(SifenTransportError):
    """La solicitud no llego al SIFEN.

    Se lanza solo cuando la falla prueba que no se escribio nada de la
    solicitud HTTP: el nombre del servidor no se pudo resolver, la conexion
    fue rechazada o el destino era inalcanzable, se agoto el tiempo al
    conectar o fallo el handshake TLS. Reenviar la misma solicitud no puede
    duplicar una operacion fiscal.
    """


class SifenTransportClosedError(SifenTransportError):
    """Error al usar un transport ya cerrado."""


class SifenTimeoutError(SifenTransportError):
    """Error de tiempo de espera durante el transporte."""


class SifenUnexpectedResponseError(SifenTransportError):
    """El SIFEN respondio algo distinto de la respuesta de la operacion.

    Cubre un sobre de otra operacion, un SOAP Fault y un cuerpo que no se
    puede interpretar (HTML de un proxy, XML truncado o un elemento que no
    corresponde al binding). Como el SIFEN pudo haber procesado la solicitud,
    el resultado de un envio con efecto fiscal queda incierto.

    Attributes:
        expected_root: nombre local de la raiz esperada.
        actual_root: nombre local de la raiz recibida (``Fault`` para un SOAP
            Fault), o ``"invalid_xml"`` si la respuesta no es XML bien formado.
        code: primer ``dCodRes``/``dCodResLot`` de la respuesta, si lo hay.
        response_message: primer ``dMsgRes``/``dMsgResLot``, si lo hay.
        raw_body: comienzo del cuerpo recibido, como texto (hasta
            :data:`MAX_CUERPO_CRUDO` caracteres), para diagnostico y
            auditoria. No forma parte del mensaje de la excepcion porque
            puede traer datos del contribuyente.
    """

    def __init__(
        self,
        *,
        expected_root: str,
        actual_root: str,
        code: str | None = None,
        response_message: str | None = None,
        raw_body: bytes | str | None = None,
    ) -> None:
        detalle = f"se esperaba {expected_root} y se recibio {actual_root}"
        if code:
            detalle += f" ({code})"
        if response_message:
            detalle += f": {response_message}"
        super().__init__(f"Respuesta inesperada del SIFEN: {detalle}")
        self.expected_root = expected_root
        self.actual_root = actual_root
        self.code = code
        self.response_message = response_message
        self.raw_body = _recortar_cuerpo(raw_body)


class SifenRejectionError(SifenError):
    """Error de rechazo funcional devuelto por SIFEN."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _recortar_cuerpo(cuerpo: bytes | str | None) -> str | None:
    """Texto del cuerpo recibido, recortado a :data:`MAX_CUERPO_CRUDO`.

    Los bytes se decodifican como UTF-8 reemplazando lo que no lo sea, para
    que el valor siempre se pueda guardar o registrar.
    """
    if cuerpo is None:
        return None
    if isinstance(cuerpo, (bytes, bytearray, memoryview)):
        cuerpo = bytes(cuerpo).decode("utf-8", errors="replace")
    return cuerpo[:MAX_CUERPO_CRUDO]
