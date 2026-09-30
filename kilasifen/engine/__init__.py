"""Fachada pública estable de PySIFEN."""

from kilasifen import __version__
from kilasifen.engine.firma import sign_xml
from kilasifen.engine.transmissao import (
    ENDPOINTS,
    PRODUCCION,
    TEST,
    ConsultaSIFEN,
    TransmissaoDE,
    TransmissaoEvento,
    get_endpoint,
)

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
