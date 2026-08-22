"""Errores tipados del SDK PySIFEN."""


class SifenError(Exception):
    """Error base del SDK."""


class SifenValidationError(SifenError):
    """Error de validacion de entrada o contrato."""


class SifenSignatureError(SifenError):
    """Error al firmar XML o preparar la firma."""


class SifenTransportError(SifenError):
    """Error al transportar mensajes SOAP."""


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
