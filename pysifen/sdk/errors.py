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
