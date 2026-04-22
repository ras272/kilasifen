"""Classe base para transmissão SOAP ao SIFEN."""
from __future__ import annotations

import tempfile
import time

from xsdata.formats.dataclass.client import Client, Config
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import (
    SerializerConfig,
)

from pysifen.sdk.errors import SifenTransportClosedError
from pysifen.transmissao.config import get_endpoint


class TransmissaoBase:
    """Base para transmissão SOAP com mTLS ao SIFEN.

    Args:
        ambiente: PRODUCCION (1) ou TEST (2)
        pkcs12_data: bytes do certificado .pfx
        pkcs12_password: senha do certificado
    """

    def __init__(
        self,
        ambiente: int,
        pkcs12_data: bytes,
        pkcs12_password: str,
        timeout: float = 30.0,
    ):
        self.ambiente = ambiente
        self.pkcs12_data = pkcs12_data
        self.pkcs12_password = pkcs12_password
        self.timeout = timeout
        self._parser = XmlParser()
        self._serializer = XmlSerializer(
            config=SerializerConfig(
                xml_declaration=True,
                encoding="UTF-8",
            )
        )
        self._cert_files = None
        self._transport = None
        self._clients = {}
        self._closed = False

    def _ensure_open(self):
        """Falha se a instancia já foi fechada."""
        if self._closed:
            raise SifenTransportClosedError(
                "A instancia de transporte ya fue cerrada"
            )

    def _get_cert_files(self) -> tuple[str, str]:
        """Extrai cert e key do PKCS12 para arquivos temporários.

        Retorna tupla (cert_path, key_path) para uso com requests/httpx.
        """
        self._ensure_open()

        if self._cert_files is not None:
            return self._cert_files

        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            pkcs12,
        )

        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            self.pkcs12_data,
            self.pkcs12_password.encode()
            if isinstance(self.pkcs12_password, str)
            else self.pkcs12_password,
        )

        cert_file = tempfile.NamedTemporaryFile(
            suffix=".pem", delete=False
        )
        key_file = tempfile.NamedTemporaryFile(
            suffix=".pem", delete=False
        )

        cert_file.write(certificate.public_bytes(Encoding.PEM))
        cert_file.close()

        key_file.write(
            private_key.private_bytes(
                Encoding.PEM,
                PrivateFormat.TraditionalOpenSSL,
                NoEncryption(),
            )
        )
        key_file.close()

        self._cert_files = (cert_file.name, key_file.name)
        return self._cert_files

    def _get_client(self, servico: str):
        """Retorna xsdata SOAP client para o serviço.

        O client é configurado com mTLS usando o certificado PKCS12.
        """
        self._ensure_open()

        if servico in self._clients:
            return self._clients[servico]

        url = get_endpoint(self.ambiente, servico)
        transport = self._get_transport()

        config = Config.from_service(None, location=url)
        client = Client(config=config, transport=transport)
        self._clients[servico] = client
        return client

    def _get_transport(self):
        """Retorna o transport compartilhado da instância."""
        self._ensure_open()

        if self._transport is not None:
            return self._transport

        cert_path, key_path = self._get_cert_files()
        self._transport = _create_transport(
            cert_path,
            key_path,
            timeout=self.timeout,
        )
        return self._transport

    def _sign_xml(self, xml: str, doc_id: str) -> str:
        """Assina XML com certificado PKCS12 (RSA-SHA256)."""
        from pysifen.assinatura import sign_xml

        return sign_xml(
            xml, self.pkcs12_data, self.pkcs12_password, doc_id
        )

    def _serialize(self, obj) -> str:
        """Serializa um objeto binding para XML string."""
        return self._serializer.render(obj)

    def _parse(self, xml: str, clazz):
        """Parseia XML string para objeto binding."""
        return self._parser.from_string(xml, clazz)

    def cleanup(self):
        """Remove arquivos temporários de certificado."""
        self.close()

    def close(self):
        """Fecha a instancia e libera recursos temporários."""
        if self._closed:
            return

        self._closed = True
        self._cleanup_transport()
        self._cleanup_cert_files()

    def _cleanup_transport(self):
        transport = self._transport
        self._transport = None
        self._clients = {}

        if transport is None:
            return

        close = getattr(transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _cleanup_cert_files(self):
        import os

        if self._cert_files:
            for path in self._cert_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            self._cert_files = None

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class RequestsTransport:
    """Transport HTTP usando requests com reintentos conservadores."""

    def __init__(
        self,
        session,
        timeout: float,
        max_retries: int = 2,
        backoff_factor: float = 0.2,
    ):
        self._session = session
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

    def close(self):
        self._session.close()

    def post(self, url, data, headers=None):
        from pysifen.sdk.errors import (
            SifenTimeoutError,
            SifenTransportError,
        )
        from requests.exceptions import (
            ConnectionError,
            HTTPError,
            RequestException,
            Timeout,
        )

        request_headers = headers or {
            "Content-Type": "text/xml; charset=utf-8"
        }

        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.post(
                    url,
                    data=data,
                    headers=request_headers,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                return response.content
            except Timeout as exc:
                if attempt >= self._max_retries:
                    raise SifenTimeoutError(
                        "Timeout ao enviar requisição SOAP"
                    ) from exc
                self._sleep_before_retry(attempt)
            except HTTPError as exc:
                if self._is_non_retryable_http_error(exc):
                    raise SifenTransportError(
                        "Falha no transporte SOAP"
                    ) from exc
                if attempt >= self._max_retries:
                    raise SifenTransportError(
                        "Falha no transporte SOAP"
                    ) from exc
                self._sleep_before_retry(attempt)
            except ConnectionError as exc:
                if attempt >= self._max_retries:
                    raise SifenTransportError(
                        "Falha no transporte SOAP"
                    ) from exc
                self._sleep_before_retry(attempt)
            except RequestException as exc:
                raise SifenTransportError(
                    "Falha no transporte SOAP"
                ) from exc

        raise SifenTransportError("Falha no transporte SOAP")

    def _is_non_retryable_http_error(self, exc):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code is not None and 400 <= status_code < 500

    def _sleep_before_retry(self, attempt: int):
        delay = self._backoff_factor * (2**attempt)
        if delay > 0:
            time.sleep(delay)

def _create_transport(
    cert_path: str,
    key_path: str,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_factor: float = 0.2,
):
    """Cria transport HTTP com mTLS para o SOAP client.

    Usa requests.Session com certificado cliente.
    """
    from requests import Session

    session = Session()
    session.cert = (cert_path, key_path)
    session.verify = True
    return RequestsTransport(
        session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
    )
