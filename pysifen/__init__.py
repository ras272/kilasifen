"""Fachada pública estable de PySIFEN."""

from pysifen.assinatura import sign_xml
from pysifen.transmissao import (
    ENDPOINTS,
    PRODUCCION,
    TEST,
    ConsultaSIFEN,
    TransmissaoDE,
    TransmissaoEvento,
    get_endpoint,
)

__version__ = "0.1.1"

__all__ = [
    "__version__",
    "sign_xml",
    "PRODUCCION",
    "TEST",
    "ENDPOINTS",
    "get_endpoint",
    "TransmissaoDE",
    "ConsultaSIFEN",
    "TransmissaoEvento",
]
