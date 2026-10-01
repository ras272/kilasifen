"""Transmision de documentos, eventos y consultas al SIFEN (SOAP 1.2 + mTLS).

Uso tipico::

    from kilasifen.engine.transmision import TEST, TransmisionDE

    with TransmisionDE(
        ambiente=TEST, pkcs12_data=pfx, pkcs12_password=clave
    ) as transmision:
        respuesta = transmision.enviar_de_xml(xml_firmado)

Necesita el extra opcional de transmision::

    pip install "kilasifen[transmision]"

Importar este paquete no requiere el extra: las dependencias pesadas se
cargan recien al enviar o firmar.
"""

from __future__ import annotations

from kilasifen.engine.transmision.config import (
    ENDPOINTS,
    PRODUCCION,
    TEST,
    get_endpoint,
)
from kilasifen.engine.transmision.consulta import ConsultaSIFEN
from kilasifen.engine.transmision.de import TransmisionDE
from kilasifen.engine.transmision.evento import TransmisionEvento

__all__ = [
    "ENDPOINTS",
    "PRODUCCION",
    "TEST",
    "ConsultaSIFEN",
    "TransmisionDE",
    "TransmisionEvento",
    "get_endpoint",
]
