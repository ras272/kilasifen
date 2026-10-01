"""Errores y avisos tipados del SDK de KilaSifen."""

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


class SifenLoteError(SifenError):
    """La consulta de un lote termino en un estado que no se puede seguir.

    Cubre los codigos de error de la consulta de lote (0360, 0363, 0340 y
    0320), un codigo no documentado y una recepcion ``0300`` sin numero de
    lote. Tambien se lanza cuando la consulta del lote ya no esta disponible
    (0364 o mas de 48 h) y no se indico como consultar cada CDC.

    Attributes:
        code: ``dCodResLot`` (o ``dCodRes`` de la recepcion) que lo causo, si
            lo hay.
        message: descripcion del problema.
        response: respuesta del SIFEN que lo causo, si la hay.
    """

    def __init__(
        self,
        code: str | None,
        message: str,
        response: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.response = response


class SifenExperimentalWarning(UserWarning):
    """Aviso de uso de un servicio sin respaldo en la documentacion oficial.

    Lo emite la consulta DTE sincronica y asincronica: la SET publica sus XSD,
    pero ni el Manual Tecnico v150 ni las Notas Tecnicas ni la Guia de
    mejores practicas documentan su direccion, sus codigos o sus plazos.
    """


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
