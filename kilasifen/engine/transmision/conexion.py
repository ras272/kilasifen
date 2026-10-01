"""Sesion HTTPS con TLS mutuo hacia el SIFEN.

El certificado cliente del emisor se presenta con un ``ssl.SSLContext``
propio, montado en la sesion ``requests`` mediante un ``HTTPAdapter``. Asi la
clave privada puede quedar en disco cifrada con una contrasena que solo vive
en memoria: ``Session.cert`` de ``requests`` no admite claves cifradas.

El contexto parte de la configuracion por defecto de urllib3 y verifica el
certificado y el nombre del servidor contra el almacen de ``requests``
(certifi), igual que una sesion sin adaptador propio.

El modulo tambien decide, con :func:`solicitud_no_enviada`, si un fallo de
``requests`` prueba que la solicitud nunca salio hacia el SIFEN. Para el
handshake TLS eso no se puede deducir del tipo de excepcion (urllib3 envuelve
igual un error del handshake y uno al leer la respuesta), asi que los sockets
del contexto marcan los errores que ocurren durante el handshake.

Este modulo importa ``requests`` y ``urllib3`` al cargarse; ``base`` lo
importa recien al crear un transporte.
"""

from __future__ import annotations

import ssl
from collections.abc import Iterator
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout
from requests.utils import DEFAULT_CA_BUNDLE_PATH, extract_zipped_paths
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from urllib3.util.ssl_ import create_urllib3_context

__all__ = ["AdaptadorTlsMutuo", "crear_sesion_tls_mutuo", "solicitud_no_enviada"]

#: Atributo que marca una excepcion ocurrida durante el handshake TLS.
_MARCA_HANDSHAKE = "_kilasifen_fallo_en_handshake"

#: Fallos que urllib3 y requests solo producen antes de escribir la solicitud:
#: resolucion de nombres (``NameResolutionError`` es un ``NewConnectionError``),
#: conexion rechazada o inalcanzable y tiempo agotado al conectar.
_FALLOS_AL_CONECTAR = (ConnectTimeout, ConnectTimeoutError, NewConnectionError)


class _SocketTlsCliente(ssl.SSLSocket):
    """``SSLSocket`` que marca los errores ocurridos durante el handshake.

    El handshake termina antes de que se escriba un solo byte de la
    solicitud HTTP, asi que un error marcado prueba que el SIFEN no la
    recibio. La excepcion se relanza sin cambiar de tipo, para que urllib3 la
    trate como siempre.
    """

    def do_handshake(self, block: bool = False) -> None:
        try:
            super().do_handshake(block)
        except OSError as exc:
            setattr(exc, _MARCA_HANDSHAKE, True)
            raise


def _crear_contexto_tls() -> ssl.SSLContext:
    """Contexto TLS de cliente que exige certificado valido del servidor."""
    contexto = create_urllib3_context()
    contexto.load_verify_locations(cafile=extract_zipped_paths(DEFAULT_CA_BUNDLE_PATH))
    contexto.sslsocket_class = _SocketTlsCliente
    return contexto


def solicitud_no_enviada(exc: BaseException) -> bool:
    """Indica si ``exc`` prueba que la solicitud no llego al SIFEN.

    Es verdadero para la resolucion de nombres fallida, la conexion rechazada
    o inalcanzable, el tiempo agotado al conectar y el handshake TLS fallido
    (con el contexto de este modulo). Cualquier otro error (timeout de
    lectura, conexion cortada a mitad de la respuesta, respuesta truncada,
    error HTTP) puede ocurrir despues de enviar el cuerpo y se considera
    ambiguo.
    """
    return any(_fallo_antes_de_enviar(eslabon) for eslabon in _eslabones(exc))


def _fallo_antes_de_enviar(exc: BaseException) -> bool:
    return isinstance(exc, _FALLOS_AL_CONECTAR) or (
        getattr(exc, _MARCA_HANDSHAKE, False) is True
    )


def _eslabones(exc: BaseException) -> Iterator[BaseException]:
    """Recorre ``exc`` y las excepciones que envuelve de forma explicita.

    Sigue ``__cause__``, el ``reason`` de ``MaxRetryError`` y los argumentos
    con que requests y urllib3 envuelven la causa. No sigue ``__context__``:
    ahi puede aparecer una excepcion ajena que el llamador estaba manejando
    cuando hizo el envio, por ejemplo un fallo de conexion anterior.
    """
    pendientes = [exc]
    vistas: set[int] = set()
    while pendientes:
        actual = pendientes.pop()
        if id(actual) in vistas:
            continue
        vistas.add(id(actual))
        yield actual
        envueltas = (actual.__cause__, getattr(actual, "reason", None), *actual.args)
        pendientes.extend(e for e in envueltas if isinstance(e, BaseException))


class AdaptadorTlsMutuo(HTTPAdapter):
    """``HTTPAdapter`` que autentica al emisor con su certificado cliente.

    El certificado y la clave se cargan en el contexto TLS recien en el
    primer envio, de modo que crear la sesion no lee archivos.

    Args:
        cert_path: ruta del certificado del emisor en PEM.
        key_path: ruta de la clave privada en PEM (cifrada o no).
        key_password: contrasena de la clave; ``None`` si no esta cifrada.
    """

    def __init__(
        self,
        cert_path: str,
        key_path: str,
        key_password: bytes | None,
        **kwargs: Any,
    ) -> None:
        # ``HTTPAdapter.__init__`` crea el pool, que ya necesita el contexto.
        self._ruta_certificado = cert_path
        self._ruta_clave = key_path
        self._contrasena_clave = key_password
        self._contexto = _crear_contexto_tls()
        self._certificado_cargado = False
        super().__init__(**kwargs)

    @property
    def contexto_tls(self) -> ssl.SSLContext:
        """Contexto TLS que usan todas las conexiones del adaptador."""
        return self._contexto

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["ssl_context"] = self._contexto
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["ssl_context"] = self._contexto
        return super().proxy_manager_for(proxy, **proxy_kwargs)

    def send(self, request: Any, **kwargs: Any) -> Any:
        """Carga el certificado cliente (una sola vez) y envia la solicitud.

        Un fallo al cargarlo (archivo ausente, contrasena incorrecta) se
        propaga tal cual: ocurre antes de abrir ninguna conexion.
        """
        self._cargar_certificado_cliente()
        return super().send(request, **kwargs)

    def _cargar_certificado_cliente(self) -> None:
        if self._certificado_cargado:
            return
        self._contexto.load_cert_chain(
            self._ruta_certificado,
            self._ruta_clave,
            password=self._contrasena_clave,
        )
        self._certificado_cargado = True


def crear_sesion_tls_mutuo(
    cert_path: str,
    key_path: str,
    key_password: bytes | None,
) -> requests.Session:
    """Sesion ``requests`` que presenta el certificado cliente en ``https://``.

    La verificacion del servidor queda activada (``verify=True``).
    """
    sesion = requests.Session()
    sesion.verify = True
    sesion.mount("https://", AdaptadorTlsMutuo(cert_path, key_path, key_password))
    return sesion
