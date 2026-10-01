"""Errores tipados del SDK de KilaSifen."""


class SifenError(Exception):
    """Error base del SDK."""


class SifenValidationError(SifenError):
    """Error de validacion de entrada o contrato."""


class SifenSignatureError(SifenError):
    """Error al firmar XML o preparar la firma."""


class SifenTransportError(SifenError):
    """Error al transportar mensajes SOAP.

    Salvo que sea una :class:`SifenRequestNotSentError`, el SIFEN pudo haber
    recibido y procesado la solicitud: el resultado de un envio con efecto
    fiscal queda incierto y hay que consultarlo antes de volver a enviar.
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
    """SIFEN responded with an envelope for a different operation."""

    def __init__(
        self,
        *,
        expected_root: str,
        actual_root: str,
        code: str | None = None,
        response_message: str | None = None,
    ) -> None:
        details = f"expected {expected_root}, received {actual_root}"
        if code:
            details += f" ({code})"
        if response_message:
            details += f": {response_message}"
        super().__init__(f"Unexpected SIFEN response: {details}")
        self.expected_root = expected_root
        self.actual_root = actual_root
        self.code = code
        self.response_message = response_message


class SifenRejectionError(SifenError):
    """Error de rechazo funcional devuelto por SIFEN."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
