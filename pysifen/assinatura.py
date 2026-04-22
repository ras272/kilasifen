"""Assinatura digital XML para SIFEN (RSA-SHA256)."""

from pysifen.sdk.signer import get_pkcs12_signer


def sign_xml(xml_input, pkcs12_data, pkcs12_password, doc_id):
    """Assina XML usando certificado PKCS12 com RSA-SHA256.

    Args:
        xml_input: XML string ou lxml Element
        pkcs12_data: bytes do .pfx
        pkcs12_password: senha (str ou bytes)
        doc_id: ID do elemento a referenciar (CDC)

    Returns:
        XML assinado como string
    """
    return get_pkcs12_signer(
        pkcs12_data,
        pkcs12_password,
    ).sign(xml_input, doc_id)
