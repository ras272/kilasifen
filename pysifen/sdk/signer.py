"""Signer reutilizable basado en material PKCS12."""
from __future__ import annotations

from functools import lru_cache

from pysifen.sdk.errors import SifenSignatureError


def _normalize_password(pkcs12_password: str | bytes) -> bytes:
    return (
        pkcs12_password.encode()
        if isinstance(pkcs12_password, str)
        else pkcs12_password
    )


def _normalize_xml(xml_input):
    from lxml import etree

    if isinstance(xml_input, (str, bytes)):
        xml_bytes = (
            xml_input.encode() if isinstance(xml_input, str) else xml_input
        )
        return etree.fromstring(xml_bytes)
    return xml_input


class Pkcs12Signer:
    """Firma XML con estado PKCS12 reutilizable."""

    def __init__(self, pkcs12_data: bytes, pkcs12_password: bytes):
        try:
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                NoEncryption,
                PrivateFormat,
                pkcs12,
            )

            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                pkcs12_data,
                pkcs12_password,
            )
            self._key_pem = private_key.private_bytes(
                Encoding.PEM,
                PrivateFormat.TraditionalOpenSSL,
                NoEncryption(),
            )
            self._cert_pem = certificate.public_bytes(Encoding.PEM)
        except Exception as exc:
            if isinstance(exc, SifenSignatureError):
                raise
            raise SifenSignatureError("Falha ao assinar XML") from exc

    def sign(self, xml_input, doc_id: str) -> str:
        try:
            from lxml import etree
            from signxml import XMLSigner, methods

            root = _normalize_xml(xml_input)
            for signature in root.findall(
                ".//{http://www.w3.org/2000/09/xmldsig#}Signature"
            ):
                parent = signature.getparent()
                if parent is not None:
                    parent.remove(signature)

            for el in root.iter("*"):
                if el.text is not None and not el.text.strip():
                    el.text = None
                if el.tail is not None and not el.tail.strip():
                    el.tail = None

            signer = XMLSigner(
                method=methods.enveloped,
                signature_algorithm="rsa-sha256",
                digest_algorithm="sha256",
                c14n_algorithm=(
                    "http://www.w3.org/2001/10/xml-exc-c14n#"
                ),
            )
            signer.namespaces = {
                None: "http://www.w3.org/2000/09/xmldsig#"
            }
            ref_uri = f"#{doc_id}" if doc_id else None
            signed = signer.sign(
                root,
                key=self._key_pem,
                cert=self._cert_pem,
                reference_uri=ref_uri,
            )

            if doc_id:
                element = signed.find(f".//*[@Id='{doc_id}']")
                signature = signed.find(
                    ".//{http://www.w3.org/2000/09/xmldsig#}Signature"
                )
                if signature is None:
                    signature = signed.find(".//Signature")
                if element is not None and signature is not None:
                    parent = element.getparent()
                    if parent is not None:
                        signature_parent = signature.getparent()
                        if signature_parent is not None:
                            signature_parent.remove(signature)
                        parent.insert(parent.index(element) + 1, signature)

            return etree.tostring(signed, encoding="unicode")
        except Exception as exc:
            if isinstance(exc, SifenSignatureError):
                raise
            raise SifenSignatureError("Falha ao assinar XML") from exc


@lru_cache(maxsize=8)
def _get_pkcs12_signer(
    pkcs12_data: bytes,
    normalized_password: bytes,
) -> Pkcs12Signer:
    return Pkcs12Signer(pkcs12_data, normalized_password)


def get_pkcs12_signer(
    pkcs12_data: bytes,
    pkcs12_password: str | bytes,
) -> Pkcs12Signer:
    """Retorna um signer reutilizable por material PKCS12."""
    return _get_pkcs12_signer(
        pkcs12_data,
        _normalize_password(pkcs12_password),
    )


def clear_pkcs12_signer_cache() -> None:
    """Limpa o cache do signer PKCS12."""
    _get_pkcs12_signer.cache_clear()
