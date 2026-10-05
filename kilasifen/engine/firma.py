"""Firma XMLDSig (RSA-SHA256, enveloped) de documentos y eventos del SIFEN.

Punto de entrada estable para firmar. El trabajo real lo hace el signer PKCS12
reutilizable de :mod:`kilasifen.engine.sdk.signer`, que cachea la clave y el
certificado ya decodificados para no reabrir el ``.pfx`` en cada documento.

Necesita el extra opcional de firma::

    pip install "kilasifen[sign]"
"""

from __future__ import annotations

from importlib.util import find_spec

# El signer solo importa sus dependencias pesadas (cryptography, signxml,
# lxml) al usarse, por lo que este import es seguro sin el extra de firma.
from kilasifen.engine.sdk.signer import get_pkcs12_signer

__all__ = ["sign_xml"]

_DEPENDENCIAS_FIRMA = ("signxml", "cryptography", "lxml")
_MENSAJE_EXTRA = (
    "La firma XML necesita dependencias opcionales ({faltantes}). "
    'Instala: pip install "kilasifen[sign]"'
)


def _verificar_dependencias() -> None:
    """Lanza ``ImportError`` con una indicacion clara si falta el extra de firma."""
    faltantes = [nombre for nombre in _DEPENDENCIAS_FIRMA if find_spec(nombre) is None]
    if faltantes:
        raise ImportError(_MENSAJE_EXTRA.format(faltantes=", ".join(faltantes)))


def sign_xml(
    xml_input,
    pkcs12_data: bytes,
    pkcs12_password: str | bytes,
    doc_id: str,
) -> str:
    """Firma un XML con el certificado PKCS12 del emisor.

    Args:
        xml_input: documento a firmar (``str``, ``bytes`` o elemento ``lxml``).
        pkcs12_data: contenido binario del archivo ``.pfx``/``.p12``.
        pkcs12_password: contrasena del PKCS12 (``str`` o ``bytes``).
        doc_id: valor del atributo ``Id`` del nodo firmado (el CDC en un
            ``DE`` o el identificador del evento); la referencia de la firma
            apunta a ``#<doc_id>`` y la ``Signature`` queda como hermana
            inmediatamente posterior de ese nodo.

    Returns:
        El XML firmado como texto.

    Raises:
        ImportError: si no esta instalado el extra ``kilasifen[sign]``.
        kilasifen.engine.sdk.errors.SifenSignatureError: si el certificado o
            el documento no permiten firmar.
    """
    _verificar_dependencias()
    return get_pkcs12_signer(pkcs12_data, pkcs12_password).sign(xml_input, doc_id)
