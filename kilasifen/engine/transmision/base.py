"""Nucleo comun de la transmision SOAP 1.2 con mTLS hacia el SIFEN.

Este modulo reune lo que comparten todas las operaciones:

* :class:`TransmisionBase`: recursos perezosos de una sesion de trabajo
  (archivos PEM para el TLS mutuo, con la clave privada cifrada, firmador
  PKCS12, transporte HTTP y clientes SOAP por servicio) y su liberacion
  ordenada;
* :class:`RequestsTransport` y :func:`_create_transport`: el transporte HTTP
  sobre ``requests`` con su politica de reintentos (la sesion con TLS mutuo
  sale de :mod:`kilasifen.engine.transmision.conexion`);
* funciones auxiliares para armar el sobre SOAP de salida y extraer el cuerpo
  util de las respuestas.

Las dependencias pesadas (``requests``, ``cryptography``, ``lxml``,
``signxml`` y el cliente SOAP de xsdata, que arrastra ``requests``) se
importan recien cuando se usan. Asi ``import kilasifen.engine`` funciona sin
el extra de transmision instalado.

Una instancia no debe compartirse entre hilos.
"""

from __future__ import annotations

import importlib
import os
import secrets
import tempfile
import time
from functools import lru_cache
from types import ModuleType
from typing import Any, TypeVar
from xml.etree import ElementTree as ET

from xsdata.exceptions import ParserError
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.engine.de.bindings.v150.ws_si_cons_de_v141 import (
    REnviConsDeRequest,
    REnviConsDeResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_dte import (
    RConsDteRequest,
    RConsDteResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_dteasync import (
    REnviConsDteAsyncRequest,
    REnviConsDteAsyncResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_lote_v141 import (
    REnviConsLoteDe,
    RResEnviConsLoteDe,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_ruc_v141 import (
    REnviConsRuc,
    RResEnviConsRuc,
)
from kilasifen.engine.de.bindings.v150.ws_si_recep_de_v150 import (
    REnviDe,
    RRetEnviDe,
)
from kilasifen.engine.de.bindings.v150.ws_si_recep_evento_v150 import (
    REnviEventoDe,
    RRetEnviEventoDe,
)
from kilasifen.engine.de.bindings.v150.ws_si_recep_lote_de_v141 import (
    REnvioLote,
    RResEnviLoteDe,
)

# Los errores se toman del submodulo y no del paquete ``kilasifen.engine.sdk``:
# este modulo se importa mientras ese paquete todavia se esta inicializando.
from kilasifen.engine.sdk.errors import (
    SifenRequestNotSentError,
    SifenTimeoutError,
    SifenTransportClosedError,
    SifenTransportError,
    SifenUnexpectedResponseError,
)
from kilasifen.engine.transmision.config import get_endpoint

__all__ = ["RequestsTransport", "TransmisionBase"]

# ---------------------------------------------------------------------------
# Constantes de protocolo y mensajes
# ---------------------------------------------------------------------------

_NS_SOAP11 = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_SOAP12 = "http://www.w3.org/2003/05/soap-envelope"

_TIPO_CONTENIDO_SOAP12 = "application/soap+xml; charset=utf-8"

_APERTURA_SOBRE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<soap:Envelope xmlns:soap="{_NS_SOAP12}">'
    "<soap:Header/>"
    "<soap:Body>"
)
_CIERRE_SOBRE = "</soap:Body></soap:Envelope>"

#: Marcas que indican que el llamador ya entrego un sobre SOAP completo.
_MARCAS_DE_SOBRE = ("<soap:Envelope", "<soapenv:Envelope")

#: Nombres locales de los elementos con codigo y mensaje de resultado.
_ETIQUETAS_CODIGO = frozenset({"dCodRes", "dCodResLot"})
_ETIQUETAS_MENSAJE = frozenset({"dMsgRes", "dMsgResLot"})

#: Raiz informada cuando una respuesta no es XML bien formado.
_RAIZ_INVALIDA = "invalid_xml"

#: Errores de xsdata al convertir un cuerpo en su binding: ``ParserError``
#: (elementos desconocidos o XML ilegible), ``TypeError`` (falta un campo
#: obligatorio) y ``ValueError``/``SyntaxError`` (conversiones, XML mal
#: formado para lxml).
_ERRORES_DE_PARSEO = (ParserError, TypeError, ValueError, SyntaxError)

_MSG_CERRADA = "La transmision SIFEN ya esta cerrada; cree una nueva instancia"
_MSG_TIMEOUT = "Se agoto el tiempo de espera de la solicitud SOAP al SIFEN"
_MSG_TRANSPORTE = "Error de transporte en la solicitud SOAP al SIFEN"
_MSG_NO_ENVIADA = (
    "No se pudo establecer la conexion con el SIFEN; la solicitud SOAP no se envio"
)
_MSG_EXTRA_FALTANTE = (
    "La transmision al SIFEN necesita dependencias opcionales que no estan "
    'instaladas ({modulo}). Instala: pip install "kilasifen[transmision]"'
)

#: Modelos de request y response que el cliente SOAP usa para cada servicio.
_MODELOS_POR_SERVICIO: dict[str, tuple[type, type]] = {
    "recep_de": (REnviDe, RRetEnviDe),
    "recep_lote": (REnvioLote, RResEnviLoteDe),
    "cons_de": (REnviConsDeRequest, REnviConsDeResponse),
    "cons_lote": (REnviConsLoteDe, RResEnviConsLoteDe),
    "cons_ruc": (REnviConsRuc, RResEnviConsRuc),
    "evento": (REnviEventoDe, RRetEnviEventoDe),
    "cons_dte": (RConsDteRequest, RConsDteResponse),
    "cons_dte_async": (REnviConsDteAsyncRequest, REnviConsDteAsyncResponse),
}

_T = TypeVar("_T", bound="TransmisionBase")

#: Tope (exclusivo) de los identificadores ``dId`` generados: quince nueves.
_TOPE_ID = 999_999_999_999_999

#: Bytes aleatorios de la contrasena que cifra la clave privada en disco.
_BYTES_CONTRASENA_CLAVE = 32


# ---------------------------------------------------------------------------
# Utilidades de modulo
# ---------------------------------------------------------------------------


def _importar_opcional(nombre: str) -> ModuleType:
    """Importa un modulo del extra de transmision con un error orientativo."""
    try:
        return importlib.import_module(nombre)
    except ImportError as exc:
        raise ImportError(_MSG_EXTRA_FALTANTE.format(modulo=nombre)) from exc


def _modulo_conexion() -> ModuleType:
    """Importa :mod:`kilasifen.engine.transmision.conexion` (necesita requests)."""
    _importar_opcional("requests")
    return importlib.import_module("kilasifen.engine.transmision.conexion")


def _validar_max_retries(max_retries: Any) -> None:
    """Rechaza un numero de reintentos negativo."""
    if isinstance(max_retries, (int, float)) and max_retries < 0:
        raise ValueError(
            f"max_retries no puede ser negativo; se recibio {max_retries!r}"
        )


def _generate_id() -> int:
    """Genera un ``dId`` a partir del reloj de pared, en milisegundos.

    El valor queda en el rango ``[0, 999999999999999)``. Dos llamadas dentro
    del mismo milisegundo devuelven el mismo numero.
    """
    milisegundos = int(time.time() * 1000)
    return milisegundos % _TOPE_ID


@lru_cache(maxsize=1)
def _parser() -> XmlParser:
    """Parser xsdata compartido por el proceso (configuracion por defecto)."""
    return XmlParser()


@lru_cache(maxsize=1)
def _serializador() -> XmlSerializer:
    """Serializador xsdata compartido: declaracion XML, UTF-8, sin sangria."""
    return XmlSerializer(
        config=SerializerConfig(encoding="UTF-8", xml_declaration=True)
    )


def _nombre_local(etiqueta: Any) -> str | None:
    """Quita el espacio de nombres ``{...}`` de una etiqueta de ElementTree."""
    if not isinstance(etiqueta, str):
        return None
    return etiqueta.rpartition("}")[2]


def _leer_xml(data: bytes | str) -> ET.Element | None:
    """Parsea con la biblioteca estandar; ``None`` si no es XML legible."""
    try:
        return ET.fromstring(data)
    except (ET.ParseError, LookupError):
        return None


def _escribir_pem_temporal(contenido: bytes) -> str:
    """Escribe ``contenido`` en un archivo ``.pem`` temporal y devuelve su ruta.

    ``mkstemp`` crea el archivo con permisos solo para el usuario actual. El
    archivo sobrevive al cierre del descriptor; lo borra quien lo pidio.
    """
    descriptor, ruta = tempfile.mkstemp(prefix="kilasifen-mtls-", suffix=".pem")
    try:
        with os.fdopen(descriptor, "wb") as archivo:
            archivo.write(contenido)
    except BaseException:
        _borrar_sin_error(ruta)
        raise
    return ruta


def _borrar_sin_error(ruta: str) -> None:
    """Borra un archivo ignorando los errores del sistema operativo."""
    try:
        os.unlink(ruta)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Sobre SOAP
# ---------------------------------------------------------------------------


def _wrap_soap_envelope(data: str | bytes) -> bytes:
    """Arma el sobre SOAP 1.2 que viaja al SIFEN.

    El payload se inserta como texto, sin parsearlo ni reserializarlo, para no
    alterar firmas XMLDSig ya calculadas. Si el payload ya trae un sobre
    (``<soap:Envelope`` o ``<soapenv:Envelope``) se envia tal cual. Una
    declaracion XML inicial se descarta porque el sobre trae la suya.

    Raises:
        UnicodeDecodeError: si ``data`` son bytes que no son UTF-8 valido.
    """
    texto = data.decode("utf-8") if isinstance(data, bytes) else data
    texto = texto.strip()

    if any(marca in texto for marca in _MARCAS_DE_SOBRE):
        return texto.encode("utf-8")

    if texto.startswith("<?xml"):
        fin_declaracion = texto.find("?>")
        if fin_declaracion != -1 and ">" not in texto[:fin_declaracion]:
            texto = texto[fin_declaracion + 2 :].strip()

    return (_APERTURA_SOBRE + texto + _CIERRE_SOBRE).encode("utf-8")


def _extract_soap_body(data: bytes) -> bytes:
    """Devuelve el primer elemento del ``Body`` SOAP de una respuesta.

    Se busca un ``Body`` entre los hijos directos de la raiz, primero en el
    espacio SOAP 1.1 y despues en el SOAP 1.2. El elemento encontrado se
    reserializa en UTF-8 sin declaracion XML. Si la respuesta no es XML, no
    trae ``Body`` o el ``Body`` no contiene elementos, se devuelve sin cambios.
    """
    raiz = _leer_xml(data)
    if raiz is None:
        return data

    cuerpo = raiz.find(f"{{{_NS_SOAP11}}}Body")
    if cuerpo is None:
        cuerpo = raiz.find(f"{{{_NS_SOAP12}}}Body")
    if cuerpo is None or len(cuerpo) == 0:
        return data

    return ET.tostring(cuerpo[0], encoding="utf-8")


def _extract_http_error_xml_body(exc: BaseException) -> bytes | None:
    """Recupera el cuerpo XML de un error HTTP, si lo tiene.

    Un 4xx/5xx del SIFEN suele traer una respuesta de negocio (por ejemplo un
    rechazo) o un ``Fault`` dentro de un sobre SOAP; ese cuerpo se trata como
    una respuesta normal. Devuelve ``None`` cuando no hay cuerpo o el cuerpo
    no es XML bien formado.
    """
    respuesta = getattr(exc, "response", None)
    if respuesta is None:
        return None
    contenido = getattr(respuesta, "content", None)
    if not contenido:
        return None
    if _leer_xml(contenido) is None:
        return None
    return _extract_soap_body(contenido)


def _response_identity(data: bytes) -> tuple[str, str | None, str | None]:
    """Identifica una respuesta sin exponer su contenido.

    Devuelve ``(raiz, codigo, mensaje)``: el nombre local del elemento raiz y
    los textos del primer ``dCodRes``/``dCodResLot`` y del primer
    ``dMsgRes``/``dMsgResLot`` con texto, en orden de documento. Ningun otro
    dato de la respuesta sale de esta funcion. Si ``data`` no es XML bien
    formado devuelve ``("invalid_xml", None, None)``.
    """
    raiz = _leer_xml(data)
    if raiz is None:
        return _RAIZ_INVALIDA, None, None

    codigo: str | None = None
    mensaje: str | None = None
    for elemento in raiz.iter():
        nombre = _nombre_local(elemento.tag)
        if elemento.text is None:
            continue
        if codigo is None and nombre in _ETIQUETAS_CODIGO:
            codigo = elemento.text
        elif mensaje is None and nombre in _ETIQUETAS_MENSAJE:
            mensaje = elemento.text
        if codigo is not None and mensaje is not None:
            break
    return _nombre_local(raiz.tag) or "", codigo, mensaje


def _get_service_models(servicio: str) -> tuple[type, type]:
    """Devuelve ``(modelo_de_request, modelo_de_response)`` del servicio.

    Raises:
        ValueError: si el servicio no tiene modelos SOAP asociados.
    """
    if servicio not in _MODELOS_POR_SERVICIO:
        raise ValueError(f"Servicio SIFEN sin modelos SOAP asociados: {servicio!r}")
    return _MODELOS_POR_SERVICIO[servicio]


# ---------------------------------------------------------------------------
# Respuestas
# ---------------------------------------------------------------------------


def _nombre_raiz(clase: type) -> str:
    """Nombre local del elemento raiz de un binding de respuesta."""
    meta = getattr(clase, "Meta", None)
    return getattr(meta, "name", None) or clase.__name__


def _respuesta_inesperada(
    datos: bytes, raiz_esperada: str
) -> SifenUnexpectedResponseError:
    """Arma el error para un cuerpo que no es la respuesta esperada."""
    raiz, codigo, mensaje = _response_identity(datos)
    return SifenUnexpectedResponseError(
        expected_root=raiz_esperada,
        actual_root=raiz,
        code=codigo,
        response_message=mensaje,
        raw_body=datos,
    )


def _parsear_respuesta(respuesta: bytes | str, clase: type) -> Any:
    """Convierte el cuerpo de una respuesta del SIFEN en una instancia de ``clase``.

    Antes de parsear comprueba que el elemento raiz sea el de ``clase``
    (xsdata no lo verifica). Un SOAP Fault, el sobre de otra operacion, un
    cuerpo que no es XML o un XML que el binding no acepta terminan en
    :class:`SifenUnexpectedResponseError`, con el comienzo del cuerpo en
    ``raw_body``; nunca en un error de xsdata.
    """
    if isinstance(respuesta, str):
        datos = respuesta.encode("utf-8")
    else:
        datos = bytes(respuesta)
    raiz_esperada = _nombre_raiz(clase)
    if _response_identity(datos)[0] != raiz_esperada:
        raise _respuesta_inesperada(datos, raiz_esperada)
    try:
        return _parser().from_bytes(datos, clase)
    except _ERRORES_DE_PARSEO as exc:
        raise _respuesta_inesperada(datos, raiz_esperada) from exc


class _ParserDeRespuestas(XmlParser):
    """Parser que el cliente SOAP de xsdata usa para leer las respuestas.

    El cliente llama ``from_bytes(respuesta, modelo_de_salida)``; este parser
    lo resuelve con :func:`_parsear_respuesta`, de modo que las operaciones
    que pasan por el cliente informan las respuestas inesperadas igual que
    las que envian XML crudo.
    """

    def from_bytes(
        self,
        source: bytes,
        clazz: type | None = None,
        ns_map: dict[str, str] | None = None,
    ) -> Any:
        if clazz is None:
            return super().from_bytes(source, clazz, ns_map)
        return _parsear_respuesta(source, clazz)


@lru_cache(maxsize=1)
def _parser_de_respuestas() -> _ParserDeRespuestas:
    """Parser de respuestas compartido por los clientes SOAP del proceso."""
    return _ParserDeRespuestas()


# ---------------------------------------------------------------------------
# Transporte HTTP
# ---------------------------------------------------------------------------


def _es_error_de_cliente(exc: BaseException) -> bool:
    """Indica si un ``HTTPError`` corresponde a un estado 4xx conocido."""
    respuesta = getattr(exc, "response", None)
    estado = getattr(respuesta, "status_code", None)
    return isinstance(estado, int) and 400 <= estado <= 499


class RequestsTransport:
    """Transporte HTTP con reintentos, compatible con el cliente SOAP de xsdata.

    Envuelve cada payload en un sobre SOAP 1.2, lo envia por POST y devuelve el
    primer elemento del ``Body`` de la respuesta. Los errores de ``requests``
    se traducen a la jerarquia :class:`SifenTransportError` y conservan la
    excepcion original como causa.

    Args:
        session: sesion ``requests`` (o un objeto con ``post`` y ``close``).
        timeout: segundos de espera de cada POST.
        max_retries: intentos adicionales permitidos.
        backoff_factor: base en segundos de la espera exponencial.
        reintentar_ambiguos: si tambien se reintentan los fallos en que el
            SIFEN pudo haber recibido la solicitud (timeout de lectura,
            conexion cortada, error 5xx). Solo es seguro para operaciones
            idempotentes; por defecto se reintentan unicamente los fallos en
            que la solicitud no salio.
    """

    def __init__(
        self,
        session: Any,
        timeout: float,
        max_retries: int = 2,
        backoff_factor: float = 0.2,
        *,
        reintentar_ambiguos: bool = False,
    ) -> None:
        self._session = session
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._reintentar_ambiguos = reintentar_ambiguos

    def close(self) -> None:
        """Cierra la sesion HTTP."""
        self._session.close()

    def post(
        self,
        url: str,
        data: str | bytes,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        """Envia ``data`` a ``url`` dentro de un sobre SOAP 1.2.

        Hace hasta ``max_retries + 1`` intentos. Siempre se reintentan los
        fallos en que la solicitud no llego al SIFEN. Con
        ``reintentar_ambiguos`` tambien los timeouts, los demas errores de
        conexion y los errores HTTP sin cuerpo XML que no sean 4xx; sin el,
        esos fallos se informan en el primer intento. Entre intentos se espera
        ``backoff_factor * 2**i`` segundos.

        Returns:
            Los bytes del primer elemento del ``Body`` de la respuesta, o la
            respuesta cruda si no es un sobre SOAP.

        Raises:
            SifenRequestNotSentError: si el ultimo intento fallo antes de
                enviar la solicitud (DNS, conexion rechazada o inalcanzable,
                tiempo agotado al conectar, handshake TLS).
            SifenTimeoutError: si se agotaron los intentos por timeout.
            SifenTransportError: ante cualquier otro fallo de ``requests``.
        """
        excepciones = _importar_opcional("requests.exceptions")

        cabeceras = dict(headers) if headers else {}
        cabeceras["Content-Type"] = _TIPO_CONTENIDO_SOAP12
        cabeceras.pop("content-type", None)

        sobre = _wrap_soap_envelope(data)
        total_intentos = self._max_retries + 1

        for intento in range(total_intentos):
            try:
                respuesta = self._session.post(
                    url,
                    data=sobre,
                    headers=cabeceras,
                    timeout=self._timeout,
                )
                respuesta.raise_for_status()
                return _extract_soap_body(respuesta.content)
            except excepciones.RequestException as exc:
                if isinstance(exc, excepciones.HTTPError):
                    cuerpo_xml = _extract_http_error_xml_body(exc)
                    if cuerpo_xml is not None:
                        return cuerpo_xml
                fallo, reintentable = self._clasificar_fallo(exc)
                if not reintentable or intento == total_intentos - 1:
                    raise fallo from exc
            self._esperar_antes_de_reintentar(intento)

        # Solo se llega aqui sin ningun intento (``max_retries`` negativo).
        raise SifenTransportError(_MSG_TRANSPORTE)

    def _clasificar_fallo(self, exc: BaseException) -> tuple[SifenTransportError, bool]:
        """Traduce un error de ``requests`` y dice si admite otro intento."""
        excepciones = _importar_opcional("requests.exceptions")
        if _modulo_conexion().solicitud_no_enviada(exc):
            return SifenRequestNotSentError(_MSG_NO_ENVIADA), True
        ambiguo = self._reintentar_ambiguos
        if isinstance(exc, excepciones.Timeout):
            return SifenTimeoutError(_MSG_TIMEOUT), ambiguo
        if isinstance(exc, excepciones.HTTPError):
            reintentable = ambiguo and not _es_error_de_cliente(exc)
            return SifenTransportError(_MSG_TRANSPORTE), reintentable
        if isinstance(exc, excepciones.ConnectionError):
            return SifenTransportError(_MSG_TRANSPORTE), ambiguo
        return SifenTransportError(_MSG_TRANSPORTE), False

    def _esperar_antes_de_reintentar(self, intento_fallido: int) -> None:
        """Espera exponencial tras el intento ``intento_fallido`` (base 0)."""
        espera = self._backoff_factor * 2**intento_fallido
        if espera > 0:
            time.sleep(espera)


def _create_transport(
    cert_path: str,
    key_path: str,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_factor: float = 0.2,
    *,
    key_password: bytes | None = None,
    reintentar_ambiguos: bool = False,
) -> RequestsTransport:
    """Crea un transporte con una sesion ``requests`` nueva y TLS mutuo.

    La sesion presenta el certificado cliente ``(cert_path, key_path)``,
    descifrando la clave con ``key_password``, y valida el certificado del
    servidor (ver :mod:`kilasifen.engine.transmision.conexion`). Los archivos
    no se leen aqui sino en el primer envio. ``reintentar_ambiguos`` se pasa
    a :class:`RequestsTransport`.
    """
    sesion = _modulo_conexion().crear_sesion_tls_mutuo(
        cert_path, key_path, key_password
    )
    return RequestsTransport(
        sesion,
        timeout=timeout,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        reintentar_ambiguos=reintentar_ambiguos,
    )


# ---------------------------------------------------------------------------
# Clase base
# ---------------------------------------------------------------------------


class TransmisionBase:
    """Recursos compartidos por las operaciones contra el SIFEN.

    El constructor no valida el ambiente ni toca disco, red o certificado:
    todo se prepara perezosamente al primer uso y se libera con
    :meth:`close` (o al salir de un bloque ``with``).

    Args:
        ambiente: :data:`~kilasifen.engine.transmision.config.PRODUCCION` o
            :data:`~kilasifen.engine.transmision.config.TEST`.
        pkcs12_data: contenido del archivo ``.pfx``/``.p12`` del emisor.
        pkcs12_password: contrasena del PKCS12 (``str`` o ``bytes``).
        timeout: segundos de espera de cada POST.
        max_retries: reintentos por envio (``0`` por defecto). Fuera de las
            consultas solo se usan para fallos en que la solicitud no llego al
            SIFEN (ver :attr:`_REINTENTA_ERRORES_AMBIGUOS`): un resultado
            incierto nunca provoca un reenvio automatico.
        retry_backoff: base en segundos de la espera exponencial.

    Raises:
        ValueError: si ``max_retries`` es negativo.
    """

    #: Si el transporte de la instancia reintenta tambien los fallos en que
    #: el SIFEN pudo haber recibido la solicitud. Falso para los envios con
    #: efecto fiscal (recepcion de DE, lotes y eventos), donde reenviar ante
    #: un resultado incierto puede duplicar la operacion; las consultas lo
    #: activan (ver ``ConsultaSIFEN``).
    _REINTENTA_ERRORES_AMBIGUOS: bool = False

    def __init__(
        self,
        ambiente: int,
        pkcs12_data: bytes,
        pkcs12_password: str | bytes | None,
        timeout: float = 30.0,
        max_retries: int = 0,
        retry_backoff: float = 0.2,
    ) -> None:
        self._closed = False
        self._cert_files: tuple[str, str] | None = None
        self._key_password: bytes | None = None
        self._signer: Any = None
        self._transport: Any = None
        self._clients: dict[str, Any] = {}

        _validar_max_retries(max_retries)

        self.ambiente = ambiente
        self.pkcs12_data = pkcs12_data
        self.pkcs12_password = pkcs12_password
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    # -- ciclo de vida -----------------------------------------------------

    def _ensure_open(self) -> None:
        """Lanza :class:`SifenTransportClosedError` si la instancia se cerro."""
        if self._closed:
            raise SifenTransportClosedError(_MSG_CERRADA)

    def close(self) -> None:
        """Libera transporte, archivos PEM y firmador. Es idempotente."""
        if self._closed:
            return
        self._closed = True
        self._cleanup_transport()
        self._cleanup_cert_files()
        self._signer = None

    def cleanup(self) -> None:
        """Sinonimo de :meth:`close`."""
        self.close()

    def _cleanup_transport(self) -> None:
        """Descarta el transporte y los clientes SOAP sin cerrar la instancia.

        El proximo uso crea una sesion HTTP nueva reutilizando los mismos
        archivos PEM.
        """
        transporte = self._transport
        self._transport = None
        self._clients = {}
        if transporte is None:
            return
        cerrar = getattr(transporte, "close", None)
        if callable(cerrar):
            try:
                cerrar()
            except Exception:
                pass

    def _cleanup_cert_files(self) -> None:
        """Borra los PEM temporales (primero el certificado, luego la clave).

        Tambien olvida la contrasena con la que se cifro la clave.
        """
        self._key_password = None
        archivos = self._cert_files
        if not archivos:
            return
        for ruta in archivos:
            try:
                os.unlink(ruta)
            except OSError:
                pass
        self._cert_files = None

    def __enter__(self: _T) -> _T:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False

    def __del__(self) -> None:
        try:
            self.cleanup()
        except Exception:
            pass

    # -- certificado y firma -----------------------------------------------

    def _get_cert_files(self) -> tuple[str, str]:
        """Devuelve ``(ruta_certificado, ruta_clave)`` en PEM para el TLS mutuo.

        La primera vez extrae del PKCS12 el certificado del firmante y su clave
        privada a dos archivos temporales que se borran en :meth:`close`. La
        clave se escribe como PKCS#8 cifrado con una contrasena aleatoria de la
        instancia que nunca toca el disco (``_key_password``): si el proceso
        muere antes de borrar el archivo, lo que queda no sirve sin ella. Los
        errores de carga del PKCS12 se propagan tal cual.
        """
        self._ensure_open()
        if self._cert_files is not None:
            return self._cert_files

        serializacion = _importar_opcional(
            "cryptography.hazmat.primitives.serialization"
        )
        cargador = _importar_opcional(
            "cryptography.hazmat.primitives.serialization.pkcs12"
        )
        contrasena = self.pkcs12_password
        if isinstance(contrasena, str):
            contrasena = contrasena.encode("utf-8")

        clave, certificado, _cadena = cargador.load_key_and_certificates(
            self.pkcs12_data, contrasena
        )
        if clave is None or certificado is None:
            raise ValueError(
                "El PKCS12 no contiene la clave privada y el certificado del firmante"
            )

        contrasena_clave = secrets.token_urlsafe(_BYTES_CONTRASENA_CLAVE).encode(
            "ascii"
        )
        certificado_pem = certificado.public_bytes(serializacion.Encoding.PEM)
        clave_pem = clave.private_bytes(
            serializacion.Encoding.PEM,
            serializacion.PrivateFormat.PKCS8,
            serializacion.BestAvailableEncryption(contrasena_clave),
        )

        ruta_certificado = _escribir_pem_temporal(certificado_pem)
        try:
            ruta_clave = _escribir_pem_temporal(clave_pem)
        except BaseException:
            _borrar_sin_error(ruta_certificado)
            raise

        self._key_password = contrasena_clave
        self._cert_files = (ruta_certificado, ruta_clave)
        return self._cert_files

    def _get_signer(self) -> Any:
        """Devuelve el firmador PKCS12 de la instancia (cacheado)."""
        self._ensure_open()
        if self._signer is None:
            from kilasifen.engine.sdk.signer import get_pkcs12_signer

            self._signer = get_pkcs12_signer(self.pkcs12_data, self.pkcs12_password)
        return self._signer

    def _sign_xml(self, xml: str, doc_id: str) -> str:
        """Firma ``xml`` (RSA-SHA256, enveloped) referenciando ``#doc_id``."""
        return self._get_signer().sign(xml, doc_id)

    # -- serializacion -----------------------------------------------------

    def _serialize(self, obj: Any, ns_map: dict[str | None, str] | None = None) -> str:
        """Serializa un binding a texto XML con declaracion y sin sangria.

        Sin ``ns_map`` xsdata asigna prefijos propios (``ns0:``...); con
        ``{None: namespace}`` ese namespace queda como espacio por defecto.
        """
        return _serializador().render(obj, ns_map=ns_map)

    def _parse(self, xml: str, clazz: type) -> Any:
        """Parsea texto XML a una instancia de ``clazz``."""
        return _parser().from_string(xml, clazz)

    def _como_respuesta(self, respuesta: Any, clase: type) -> Any:
        """Normaliza lo devuelto por el transporte o el cliente a ``clase``.

        Raises:
            SifenUnexpectedResponseError: si el cuerpo no es una respuesta de
                ``clase`` (SOAP Fault, sobre de otra operacion, cuerpo
                ilegible).
        """
        if isinstance(respuesta, clase):
            return respuesta
        return _parsear_respuesta(respuesta, clase)

    # -- transporte y clientes SOAP ----------------------------------------

    def _get_transport(self) -> Any:
        """Devuelve el transporte HTTP de la instancia, creandolo si hace falta.

        La configuracion (timeout y reintentos) se toma de la instancia en el
        momento de crear el transporte.
        """
        self._ensure_open()
        if self._transport is None:
            ruta_certificado, ruta_clave = self._get_cert_files()
            self._transport = _create_transport(
                ruta_certificado,
                ruta_clave,
                timeout=self.timeout,
                max_retries=self.max_retries,
                backoff_factor=self.retry_backoff,
                key_password=self._key_password,
                reintentar_ambiguos=self._REINTENTA_ERRORES_AMBIGUOS,
            )
        return self._transport

    def _get_client(self, servicio: str) -> Any:
        """Devuelve el cliente SOAP de xsdata para ``servicio`` (cacheado).

        Todos los clientes de la instancia comparten el mismo transporte. Las
        respuestas se leen con :class:`_ParserDeRespuestas`: una respuesta
        inesperada llega como :class:`SifenUnexpectedResponseError`.
        """
        self._ensure_open()
        if servicio in self._clients:
            return self._clients[servicio]

        url = get_endpoint(self.ambiente, servicio)
        transporte = self._get_transport()
        modelo_entrada, modelo_salida = _get_service_models(servicio)

        cliente_xsdata = _importar_opcional("xsdata.formats.dataclass.client")
        configuracion = cliente_xsdata.Config(
            style="document",
            location=url,
            transport=cliente_xsdata.TransportTypes.SOAP,
            soap_action="",
            input=modelo_entrada,
            output=modelo_salida,
            encoding=None,
        )
        cliente = cliente_xsdata.Client(
            config=configuracion,
            transport=transporte,
            parser=_parser_de_respuestas(),
        )
        self._clients[servicio] = cliente
        return cliente

    def _send_raw_xml(self, servicio: str, xml: str | bytes) -> bytes:
        """Envia ``xml`` tal cual al servicio y devuelve el cuerpo de la respuesta."""
        url = get_endpoint(self.ambiente, servicio)
        transporte = self._get_transport()
        return transporte.post(url, data=xml)

    def _send_safe_query(
        self,
        servicio: str,
        request: Any,
        response_type: type,
    ) -> Any:
        """Ejecuta una consulta verificando que la respuesta sea la esperada.

        En el ambiente de pruebas del SIFEN se observaron respuestas que llegan
        con el sobre de otra operacion. Como una consulta no tiene efecto
        fiscal, ante esa situacion se abre una conexion nueva y se vuelve a
        enviar el mismo request (mismo ``dId``), hasta ``max_retries + 1``
        veces. Si nunca llega la respuesta esperada se lanza
        :class:`SifenUnexpectedResponseError`. Una respuesta con la raiz
        esperada que el binding no acepta no se reintenta: se informa enseguida
        con el mismo error.
        """
        _validar_max_retries(self.max_retries)

        texto = self._serialize(request)
        raiz_esperada = _nombre_raiz(response_type)
        total_intentos = self.max_retries + 1

        for intento in range(total_intentos):
            respuesta = self._send_raw_xml(servicio, texto)
            try:
                return _parsear_respuesta(respuesta, response_type)
            except SifenUnexpectedResponseError as error:
                otra_operacion = error.actual_root != raiz_esperada
                if not otra_operacion or intento == total_intentos - 1:
                    raise
            self._cleanup_transport()
            espera = self.retry_backoff * 2**intento
            if espera > 0:
                time.sleep(espera)

        # Inalcanzable con un ``max_retries`` valido: siempre hay un intento.
        raise ValueError(f"max_retries no es valido; se recibio {self.max_retries!r}")
