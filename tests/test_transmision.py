"""Pruebas de ``kilasifen.engine.transmision`` (SOAP 1.2 con mTLS hacia el SIFEN).

Cubren la tabla de endpoints, la API publica del paquete, el ciclo de vida de
las instancias, el transporte HTTP y su politica de reintentos, los sobres
SOAP, la consulta segura, las consultas, el envio de documentos y lotes y los
eventos.

Ninguna prueba accede a la red: los POST se reemplazan en ``_session.post``
del transporte o en ``requests.Session.post`` (atributo de clase). Las pruebas
que necesitan un PKCS#12 real usan el certificado efimero que genera
``tests/conftest.py``.

Los fragmentos de los mensajes de error que se comparan son los "fragmentos
estables" que fija la especificacion del motor (tabla 15.4 de S1).
"""

from __future__ import annotations

import base64
import decimal
import importlib
import io
import json
import os
import re
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from decimal import Decimal
from http.client import RemoteDisconnected
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from xsdata.exceptions import ParserError
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.engine.de.bindings.v150.evento_v150 import TgGroupGesEve
from kilasifen.engine.de.bindings.v150.fe_v141 import RDe
from kilasifen.engine.de.bindings.v150.prot_proces_de_v150 import RProtDe
from kilasifen.engine.de.bindings.v150.prot_proces_eventos_v141 import (
    TgResProc,
    TgResProcEve,
)
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
    TContenedorRuc,
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
from kilasifen.engine.sdk.errors import (
    MAX_CUERPO_CRUDO,
    SifenError,
    SifenRequestNotSentError,
    SifenSignatureError,
    SifenTimeoutError,
    SifenTransportClosedError,
    SifenTransportError,
    SifenUnexpectedResponseError,
)
from kilasifen.engine.sdk.signer import clear_pkcs12_signer_cache
from kilasifen.engine.transmision import base
from kilasifen.engine.transmision import de as modulo_de
from kilasifen.engine.transmision import evento as modulo_evento
from kilasifen.engine.transmision.base import TransmisionBase
from kilasifen.engine.transmision.config import (
    ENDPOINTS,
    PRODUCCION,
    TEST,
    get_endpoint,
)
from kilasifen.engine.transmision.consulta import ConsultaSIFEN, _normalize_ruc
from kilasifen.engine.transmision.de import (
    MAX_BYTES_MENSAJE_LOTE,
    MAX_LOTE,
    NOMBRE_ARCHIVO_LOTE,
    TransmisionDE,
    _build_enviar_de_request_xml,
    _build_lote_zip,
)
from kilasifen.engine.transmision.evento import TransmisionEvento
from tests._muestras import FACTURA, NOTA_CREDITO

requests = pytest.importorskip(
    "requests", reason="las pruebas de transmision requieren el extra 'transmision'"
)
etree = pytest.importorskip(
    "lxml.etree", reason="las pruebas de transmision requieren lxml"
)
# El cliente SOAP de xsdata importa ``requests`` al cargarse: va despues del skip.
cliente_xsdata = importlib.import_module("xsdata.formats.dataclass.client")
conexion = importlib.import_module("kilasifen.engine.transmision.conexion")
urllib3_exc = importlib.import_module("urllib3.exceptions")


# ---------------------------------------------------------------------------
# Constantes de prueba
# ---------------------------------------------------------------------------

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[1]
RUTA_CERTIFICADO_PRUEBA = Path(__file__).with_name("test_cert.pfx")
CONTRASENA_CERTIFICADO_PRUEBA = "test1234"
CONTRASENA_CLAVE_FICTICIA = b"contrasena-ficticia-de-la-clave-pem"

NS_SIFEN = "http://ekuatia.set.gov.py/sifen/xsd"
NS_SOAP11 = "http://schemas.xmlsoap.org/soap/envelope/"
NS_SOAP12 = "http://www.w3.org/2003/05/soap-envelope"
NS_XMLDSIG = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION_RECEPCION = f"{NS_SIFEN} siRecepDE_v150.xsd"
TIPO_CONTENIDO_SOAP12 = "application/soap+xml; charset=utf-8"

APERTURA_SOBRE = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
    b"<soap:Header/><soap:Body>"
)
CIERRE_SOBRE = b"</soap:Body></soap:Envelope>"

FECHA_PROCESO = "2026-03-14T09:26:53-03:00"
RUC_NORMALIZADO = "80024135"

SERVICIOS = (
    "recep_de",
    "recep_lote",
    "cons_de",
    "cons_lote",
    "cons_ruc",
    "evento",
    "cons_dte",
    "cons_dte_async",
)

URLS_OFICIALES = [
    (PRODUCCION, "recep_de", "https://sifen.set.gov.py/de/ws/sync/recibe.wsdl"),
    (
        PRODUCCION,
        "recep_lote",
        "https://sifen.set.gov.py/de/ws/async/recibe-lote.wsdl",
    ),
    (PRODUCCION, "cons_de", "https://sifen.set.gov.py/de/ws/consultas/consulta.wsdl"),
    (
        PRODUCCION,
        "cons_lote",
        "https://sifen.set.gov.py/de/ws/consultas/consulta-lote.wsdl",
    ),
    (
        PRODUCCION,
        "cons_ruc",
        "https://sifen.set.gov.py/de/ws/consultas/consulta-ruc.wsdl",
    ),
    (PRODUCCION, "evento", "https://sifen.set.gov.py/de/ws/eventos/evento.wsdl"),
    (
        PRODUCCION,
        "cons_dte",
        "https://sifen.set.gov.py/de/ws/consultas/consulta-dte.wsdl",
    ),
    (
        PRODUCCION,
        "cons_dte_async",
        "https://sifen.set.gov.py/de/ws/consultas/consulta-dte-async.wsdl",
    ),
    (TEST, "recep_de", "https://sifen-test.set.gov.py/de/ws/sync/recibe.wsdl"),
    (
        TEST,
        "recep_lote",
        "https://sifen-test.set.gov.py/de/ws/async/recibe-lote.wsdl",
    ),
    (
        TEST,
        "cons_de",
        "https://sifen-test.set.gov.py/de/ws/consultas/consulta.wsdl",
    ),
    (
        TEST,
        "cons_lote",
        "https://sifen-test.set.gov.py/de/ws/consultas/consulta-lote.wsdl",
    ),
    (
        TEST,
        "cons_ruc",
        "https://sifen-test.set.gov.py/de/ws/consultas/consulta-ruc.wsdl",
    ),
    (TEST, "evento", "https://sifen-test.set.gov.py/de/ws/eventos/evento.wsdl"),
    (
        TEST,
        "cons_dte",
        "https://sifen-test.set.gov.py/de/ws/consultas/consulta-dte.wsdl",
    ),
    (
        TEST,
        "cons_dte_async",
        "https://sifen-test.set.gov.py/de/ws/consultas/consulta-dte-async.wsdl",
    ),
]

MODELOS_POR_SERVICIO = [
    ("recep_de", REnviDe, RRetEnviDe),
    ("recep_lote", REnvioLote, RResEnviLoteDe),
    ("cons_de", REnviConsDeRequest, REnviConsDeResponse),
    ("cons_lote", REnviConsLoteDe, RResEnviConsLoteDe),
    ("cons_ruc", REnviConsRuc, RResEnviConsRuc),
    ("evento", REnviEventoDe, RRetEnviEventoDe),
    ("cons_dte", RConsDteRequest, RConsDteResponse),
    ("cons_dte_async", REnviConsDteAsyncRequest, REnviConsDteAsyncResponse),
]

# Respuesta de recepcion de DE que llega, por error, a una consulta de RUC.
RESPUESTA_AJENA_0160 = (
    "<rRetEnviDe xmlns='http://ekuatia.set.gov.py/sifen/xsd'>\n"
    "  <rProtDe>\n"
    f"    <dFecProc>{FECHA_PROCESO}</dFecProc>\n"
    "    <dEstRes>Rechazado</dEstRes>\n"
    "    <gResProc>\n"
    "      <dCodRes>0160</dCodRes>\n"
    "      <dMsgRes>XML Mal Formado.</dMsgRes>\n"
    "    </gResProc>\n"
    "  </rProtDe>\n"
    "</rRetEnviDe>\n"
).encode("utf-8")

RESPUESTA_RUC_0502 = (
    "<rResEnviConsRUC xmlns='http://ekuatia.set.gov.py/sifen/xsd'>\n"
    "  <dCodRes>0502</dCodRes>\n"
    "  <dMsgRes>RUC encontrado</dMsgRes>\n"
    "</rResEnviConsRUC>\n"
).encode("utf-8")

CUERPO_RUC_PREFIJADO = (
    f'<q:rResEnviConsRUC xmlns:q="{NS_SIFEN}">'
    "<q:dCodRes>0502</q:dCodRes><q:dMsgRes>RUC encontrado</q:dMsgRes>"
    "</q:rResEnviConsRUC>"
)
CUERPO_RET_ENVI_DE_PREFIJADO = (
    f'<q:rRetEnviDe xmlns:q="{NS_SIFEN}"><q:rProtDe>'
    f"<q:dFecProc>{FECHA_PROCESO}</q:dFecProc><q:dEstRes>Rechazado</q:dEstRes>"
    "<q:gResProc><q:dCodRes>0160</q:dCodRes>"
    "<q:dMsgRes>XML Mal Formado.</q:dMsgRes></q:gResProc>"
    "</q:rProtDe></q:rRetEnviDe>"
)

_SERIALIZADOR_PRUEBA = XmlSerializer(config=SerializerConfig(xml_declaration=True))


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _cdc_ficticio(semilla: int) -> str:
    """CDC inventado de 44 digitos (no corresponde a ningun documento real)."""
    return f"7{semilla:043d}"


def _rde_sifen(doc_id: str, extra: str = "") -> str:
    """``rDE`` minimo con el espacio SIFEN como espacio de nombres por defecto."""
    return (
        f'<rDE xmlns="{NS_SIFEN}"><dVerFor>150</dVerFor>'
        f'<DE Id="{doc_id}"><dDVId>3</dDVId></DE>{extra}</rDE>'
    )


def _rde_lote(
    cdc: str,
    tipo: str = FACTURA.tipo,
    ruc: str = FACTURA.ruc_emisor,
    extra: str = "",
) -> str:
    """``rDE`` minimo con lo que valida el lote: CDC, ``iTiDE`` y ``dRucEm``.

    Usa el tipo y el RUC emisor ficticios de la muestra de factura.
    """
    return (
        f'<rDE xmlns="{NS_SIFEN}"><dVerFor>150</dVerFor><DE Id="{cdc}">'
        f"<gTimb><iTiDE>{tipo}</iTiDE></gTimb>"
        f"<gDatGralOpe><gEmis><dRucEm>{ruc}</dRucEm></gEmis></gDatGralOpe>"
        f"</DE>{extra}</rDE>"
    )


def _rde_lote_de_binding(rde: Any, **_kwargs: Any) -> str:
    """Efecto de ``_serialize`` en las pruebas de lote: ``rDE`` con el ``Id``."""
    return _rde_lote(rde.DE.Id)


def _abrir_zip_lote(datos: bytes) -> tuple[list[str], bytes]:
    """Nombres de las entradas del ZIP de un lote y el contenido de la primera."""
    with zipfile.ZipFile(io.BytesIO(datos)) as archivo:
        nombres = archivo.namelist()
        return nombres, archivo.read(nombres[0])


def _xml_de_binding(objeto: Any) -> str:
    """Serializa un binding sin pasar por el motor bajo prueba."""
    return _SERIALIZADOR_PRUEBA.render(objeto)


def _sobre_soap12(cuerpo: str) -> bytes:
    """Sobre SOAP 1.2 de respuesta con prefijo propio."""
    return (
        f'<e:Envelope xmlns:e="{NS_SOAP12}"><e:Body>{cuerpo}</e:Body></e:Envelope>'
    ).encode("utf-8")


def _ret_envi_de_minimo() -> RRetEnviDe:
    """Respuesta de recepcion con lo minimo que exige el binding."""
    return RRetEnviDe(rProtDe=RProtDe(dFecProc=FECHA_PROCESO))


def _hijo_local(elemento: Any, nombre: str) -> Any:
    """Primer descendiente cuyo nombre local es ``nombre`` (lxml o ElementTree)."""
    for nodo in elemento.iter():
        if isinstance(nodo.tag, str) and nodo.tag.rpartition("}")[2] == nombre:
            return nodo
    raise AssertionError(f"no se encontro el elemento {nombre!r}")


def _ejecutar_python(codigo: str, *argumentos: str) -> subprocess.CompletedProcess:
    """Ejecuta ``codigo`` en un interprete limpio que importa este repositorio."""
    entorno = dict(os.environ)
    rutas = [str(RAIZ_REPOSITORIO)]
    if entorno.get("PYTHONPATH"):
        rutas.append(entorno["PYTHONPATH"])
    entorno["PYTHONPATH"] = os.pathsep.join(rutas)
    return subprocess.run(
        [sys.executable, "-c", codigo, *argumentos],
        cwd=RAIZ_REPOSITORIO,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _certificado_pem(pfx: bytes) -> str:
    """Certificado del firmante del PKCS#12 de prueba, en PEM."""
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

    _clave, certificado, _cadena = pkcs12.load_key_and_certificates(
        pfx, CONTRASENA_CERTIFICADO_PRUEBA.encode("ascii")
    )
    return certificado.public_bytes(Encoding.PEM).decode("ascii")


def _firmar_con_pfx(pfx: bytes, xml: str, doc_id: str) -> str:
    """Firma con ``TransmisionBase._sign_xml`` real y el PKCS#12 de prueba."""
    with TransmisionBase(
        ambiente=TEST,
        pkcs12_data=pfx,
        pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
    ) as firmante:
        return firmante._sign_xml(xml, doc_id)


def _verificar_firma(rde: Any, certificado_pem: str) -> None:
    """Verifica con signxml la firma enveloped de un ``rDE`` (lanza si falla)."""
    signxml = pytest.importorskip("signxml")
    signxml.XMLVerifier().verify(
        etree.tostring(rde), x509_cert=certificado_pem, id_attribute="Id"
    )


def _verificar_firma_en_solicitud(solicitud: bytes, certificado_pem: str) -> None:
    """Verifica con signxml la firma sobre los bytes completos de ``rEnviDe``,
    tal como los recibe el SIFEN (lanza si falla)."""
    signxml = pytest.importorskip("signxml")
    signxml.XMLVerifier().verify(
        solicitud, x509_cert=certificado_pem, id_attribute="Id"
    )


def _rde_dentro_de_solicitud(solicitud: bytes) -> Any:
    """Extrae ``rEnviDe/xDE/rDE`` de los bytes de una solicitud."""
    raiz = etree.fromstring(solicitud)
    rde = raiz.find(f"{{{NS_SIFEN}}}xDE/{{{NS_SIFEN}}}rDE")
    assert rde is not None, "la solicitud no contiene xDE/rDE"
    return rde


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------


class Registrador:
    """Doble invocable: guarda cada llamada y responde con un valor fijo.

    Si se indica ``efecto``, la respuesta es lo que devuelva (o lance) esa
    funcion con los mismos argumentos. No es un descriptor, por lo que
    instalado como atributo de clase recibe solo los argumentos explicitos.
    """

    def __init__(
        self,
        resultado: Any = None,
        efecto: Callable[..., Any] | None = None,
    ) -> None:
        self.resultado = resultado
        self.efecto = efecto
        self.llamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.llamadas.append((args, kwargs))
        if self.efecto is not None:
            return self.efecto(*args, **kwargs)
        return self.resultado

    @property
    def veces(self) -> int:
        return len(self.llamadas)

    @property
    def argumentos(self) -> list[tuple[Any, ...]]:
        return [args for args, _kwargs in self.llamadas]


class Secuencia:
    """Entrega (o lanza) los pasos en orden; el ultimo se repite sin fin."""

    def __init__(self, *pasos: Any) -> None:
        if not pasos:
            raise ValueError("la secuencia necesita al menos un paso")
        self._pasos = list(pasos)

    def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        paso = self._pasos.pop(0) if len(self._pasos) > 1 else self._pasos[0]
        if isinstance(paso, BaseException):
            raise paso
        return paso


class RespuestaHttpFalsa:
    """Respuesta HTTP minima: ``content``, ``status_code`` opcional y
    ``raise_for_status`` que lanza ``HTTPError`` con ``response=self`` ante un
    estado mayor o igual a 400."""

    def __init__(self, content: bytes = b"", status_code: int | None = 200) -> None:
        self.content = content
        if status_code is not None:
            self.status_code = status_code

    def raise_for_status(self) -> None:
        estado = getattr(self, "status_code", None)
        if estado is not None and estado >= 400:
            raise requests.exceptions.HTTPError(f"estado HTTP {estado}", response=self)


class RespuestaSinEstado:
    """Respuesta sin ``status_code`` cuyo ``HTTPError`` puede no traer respuesta."""

    def __init__(self, con_respuesta_adjunta: bool) -> None:
        self.content = b""
        self._con_respuesta_adjunta = con_respuesta_adjunta

    def raise_for_status(self) -> None:
        if self._con_respuesta_adjunta:
            raise requests.exceptions.HTTPError(
                "falla sin estado", response=SimpleNamespace()
            )
        raise requests.exceptions.HTTPError("falla sin estado")


class SesionProgramada:
    """Reemplazo de ``_session.post`` con la firma exacta que usa el transporte.

    La URL solo se acepta posicional y el resto solo por nombre, que es la
    forma en que el transporte debe invocar a la sesion.
    """

    def __init__(self, pasos: Secuencia) -> None:
        self._pasos = pasos
        self.llamadas: list[SimpleNamespace] = []

    def post(
        self,
        url: str,
        /,
        *,
        data: Any,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        self.llamadas.append(
            SimpleNamespace(
                url=url,
                data=data,
                headers=None if headers is None else dict(headers),
                timeout=timeout,
            )
        )
        return self._pasos()


class RedSimulada:
    """Registro de los POST hechos por ``requests.Session`` (parche de clase)."""

    def __init__(self, pasos: Secuencia) -> None:
        self._pasos = pasos
        self.llamadas: list[SimpleNamespace] = []

    def registrar(
        self,
        sesion: Any,
        url: str,
        data: Any,
        headers: dict[str, str] | None,
        timeout: float | None,
    ) -> Any:
        # Se guarda la referencia a la sesion (no su id) para que una sesion
        # liberada no pueda confundirse con una nueva.
        self.llamadas.append(
            SimpleNamespace(
                sesion=sesion,
                url=url,
                data=data,
                headers=dict(headers or {}),
                timeout=timeout,
            )
        )
        return self._pasos()


class ClienteSoapFalso:
    """Cliente SOAP doble: registra servicios pedidos y requests enviados."""

    def __init__(self) -> None:
        self.servicios: list[str] = []
        self.envios: list[Any] = []
        self.respuesta: Any = None
        self.error: BaseException | None = None

    def send(self, request: Any, /) -> Any:
        self.envios.append(request)
        if self.error is not None:
            raise self.error
        return self.respuesta


class TransporteFalso:
    """Transporte doble con ``_session``, ``post`` y ``close`` observables."""

    def __init__(self) -> None:
        self._session = SimpleNamespace()
        self.respuesta = b"<respuestaFicticia/>"
        self.envios: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.cierres = 0
        self.error_al_cerrar: BaseException | None = None

    def post(self, *args: Any, **kwargs: Any) -> bytes:
        self.envios.append((args, kwargs))
        return self.respuesta

    def close(self) -> None:
        self.cierres += 1
        if self.error_al_cerrar is not None:
            raise self.error_al_cerrar


class ClienteXsdataFalso:
    """Reemplazo de ``xsdata...client.Client``: solo acepta argumentos nombrados."""

    def __init__(self, *, config: Any, transport: Any, parser: Any) -> None:
        self.config = config
        self.transport = transport
        self.parser = parser

    def send(self, request: Any, /) -> Any:
        return None


class FabricasFalsas:
    """Registro de lo que crean los reemplazos de transporte y certificado."""

    def __init__(self) -> None:
        self.transportes: list[TransporteFalso] = []
        self.llamadas_transporte: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.lecturas_certificado = 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def credenciales_ficticias() -> dict[str, Any]:
    """Ambiente de pruebas y material PKCS#12 deliberadamente invalido."""
    return {
        "ambiente": TEST,
        "pkcs12_data": b"pfx-ficticio-que-no-es-un-pkcs12",
        "pkcs12_password": "clave-ficticia",
    }


def _abrir(clase: type, credenciales: dict[str, Any]) -> Iterator[Any]:
    instancia = clase(**credenciales)
    try:
        yield instancia
    finally:
        instancia.close()


@pytest.fixture
def transmision_base(credenciales_ficticias: dict[str, Any]) -> Iterator[Any]:
    yield from _abrir(TransmisionBase, credenciales_ficticias)


@pytest.fixture
def transmision_de(credenciales_ficticias: dict[str, Any]) -> Iterator[Any]:
    yield from _abrir(TransmisionDE, credenciales_ficticias)


@pytest.fixture
def transmision_evento(credenciales_ficticias: dict[str, Any]) -> Iterator[Any]:
    yield from _abrir(TransmisionEvento, credenciales_ficticias)


@pytest.fixture
def consulta(credenciales_ficticias: dict[str, Any]) -> Iterator[Any]:
    yield from _abrir(ConsultaSIFEN, credenciales_ficticias)


@pytest.fixture
def cliente_soap_falso(monkeypatch: pytest.MonkeyPatch) -> ClienteSoapFalso:
    """Reemplaza ``TransmisionBase._get_client`` por un cliente doble."""
    cliente = ClienteSoapFalso()

    def obtener_cliente(self: TransmisionBase, servicio: str) -> ClienteSoapFalso:
        cliente.servicios.append(servicio)
        return cliente

    monkeypatch.setattr(TransmisionBase, "_get_client", obtener_cliente)
    return cliente


@pytest.fixture
def fabricas_falsas(monkeypatch: pytest.MonkeyPatch) -> FabricasFalsas:
    """Reemplaza ``_create_transport``, ``Client`` de xsdata y ``_get_cert_files``."""
    fabricas = FabricasFalsas()

    def crear_transporte(*args: Any, **kwargs: Any) -> TransporteFalso:
        fabricas.llamadas_transporte.append((args, kwargs))
        nuevo = TransporteFalso()
        fabricas.transportes.append(nuevo)
        return nuevo

    def rutas_de_certificado(self: TransmisionBase) -> tuple[str, str]:
        fabricas.lecturas_certificado += 1
        self._key_password = CONTRASENA_CLAVE_FICTICIA
        return ("cert.pem", "key.pem")

    monkeypatch.setattr(base, "_create_transport", crear_transporte)
    monkeypatch.setattr(cliente_xsdata, "Client", ClienteXsdataFalso)
    monkeypatch.setattr(TransmisionBase, "_get_cert_files", rutas_de_certificado)
    return fabricas


@pytest.fixture
def respuesta_http() -> type[RespuestaHttpFalsa]:
    """Fabrica de respuestas HTTP falsas."""
    return RespuestaHttpFalsa


@pytest.fixture
def transporte() -> Iterator[Callable[..., Any]]:
    """Fabrica de transportes reales; cierra todo lo que crea.

    Salvo que se pida otra cosa, el transporte reintenta tambien los fallos
    ambiguos (como el de una consulta), para ejercitar toda la politica.
    """
    creados: list[Any] = []

    def crear(
        max_retries: int = 0,
        *,
        timeout: float = 0.01,
        backoff_factor: float = 0.0,
        rutas: tuple[str, str] = ("cert.pem", "key.pem"),
        por_defecto: bool = False,
        reintentar_ambiguos: bool = True,
    ) -> Any:
        if por_defecto:
            nuevo = base._create_transport(*rutas)
        else:
            nuevo = base._create_transport(
                *rutas,
                timeout=timeout,
                max_retries=max_retries,
                backoff_factor=backoff_factor,
                reintentar_ambiguos=reintentar_ambiguos,
            )
        creados.append(nuevo)
        return nuevo

    yield crear
    for creado in creados:
        creado.close()


@pytest.fixture
def sesion_programada(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., SesionProgramada]:
    """Programa ``_session.post`` de un transporte con una secuencia de pasos."""

    def programar(transporte_http: Any, *pasos: Any) -> SesionProgramada:
        sesion = SesionProgramada(Secuencia(*pasos))
        monkeypatch.setattr(transporte_http._session, "post", sesion.post)
        return sesion

    return programar


@pytest.fixture
def esperas(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Reemplaza ``time.sleep`` por un registro de demoras."""
    demoras: list[float] = []
    monkeypatch.setattr(time, "sleep", demoras.append)
    return demoras


@pytest.fixture
def borrados(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Reemplaza ``os.unlink`` por un registro de rutas."""
    rutas: list[str] = []
    monkeypatch.setattr(os, "unlink", rutas.append)
    return rutas


@pytest.fixture
def rde_simulado() -> Callable[[Any], SimpleNamespace]:
    """Fabrica de objetos con atributo ``DE.Id``."""

    def fabricar(cdc: Any) -> SimpleNamespace:
        return SimpleNamespace(DE=SimpleNamespace(Id=cdc))

    return fabricar


@pytest.fixture
def pfx_de_prueba() -> bytes:
    """Bytes del PKCS#12 efimero de ``tests/conftest.py``."""
    pytest.importorskip("signxml", reason="requiere signxml (extra 'sign')")
    pytest.importorskip("cryptography", reason="requiere cryptography")
    if not RUTA_CERTIFICADO_PRUEBA.exists():
        pytest.skip("no existe el PKCS#12 de pruebas")
    return RUTA_CERTIFICADO_PRUEBA.read_bytes()


@pytest.fixture
def cargas_pkcs12(monkeypatch: pytest.MonkeyPatch) -> Iterator[Registrador]:
    """Cuenta las cargas PKCS#12 con la cache del firmador limpia."""
    modulo_pkcs12 = pytest.importorskip(
        "cryptography.hazmat.primitives.serialization.pkcs12"
    )
    contador = Registrador(efecto=modulo_pkcs12.load_key_and_certificates)
    monkeypatch.setattr(modulo_pkcs12, "load_key_and_certificates", contador)
    clear_pkcs12_signer_cache()
    yield contador
    clear_pkcs12_signer_cache()


@pytest.fixture
def red_simulada(monkeypatch: pytest.MonkeyPatch) -> Callable[..., RedSimulada]:
    """Integracion sin red: cliente xsdata y transporte reales, POST simulado."""

    def programar(*pasos: Any) -> RedSimulada:
        red = RedSimulada(Secuencia(*pasos))

        def post(
            sesion: Any,
            url: str,
            /,
            *,
            data: Any = None,
            headers: dict[str, str] | None = None,
            timeout: float | None = None,
        ) -> Any:
            return red.registrar(sesion, url, data, headers, timeout)

        monkeypatch.setattr(requests.Session, "post", post)
        monkeypatch.setattr(
            TransmisionBase,
            "_get_cert_files",
            lambda self: ("cert-ficticio.pem", "clave-ficticia.pem"),
        )
        return red

    return programar


# ---------------------------------------------------------------------------
# Configuracion de endpoints
# ---------------------------------------------------------------------------


class TestConfiguracionEndpoints:
    def test_endpoints_definidos_para_ambos_ambientes(self) -> None:
        """L01."""
        assert PRODUCCION in ENDPOINTS
        assert TEST in ENDPOINTS

    @pytest.mark.parametrize("servicio", SERVICIOS)
    def test_produccion_expone_los_ocho_servicios_https(self, servicio: str) -> None:
        """L02."""
        assert servicio in ENDPOINTS[PRODUCCION]
        assert ENDPOINTS[PRODUCCION][servicio].startswith("https://")

    def test_urls_de_test_apuntan_a_sifen_test(self) -> None:
        """L03."""
        for url in ENDPOINTS[TEST].values():
            assert "sifen-test" in url

    def test_get_endpoint_produccion_usa_dominio_oficial(self) -> None:
        """L04."""
        assert "sifen.set.gov.py" in get_endpoint(PRODUCCION, "recep_de")

    def test_get_endpoint_test_usa_dominio_de_pruebas(self) -> None:
        """L05."""
        assert "sifen-test" in get_endpoint(TEST, "recep_de")

    def test_endpoint_consulta_ruc_test_es_ruta_oficial(self) -> None:
        """L06."""
        assert (
            get_endpoint(TEST, "cons_ruc")
            == "https://sifen-test.set.gov.py/de/ws/consultas/consulta-ruc.wsdl"
        )

    def test_endpoint_consulta_lote_test_es_ruta_oficial(self) -> None:
        """L07."""
        assert (
            get_endpoint(TEST, "cons_lote")
            == "https://sifen-test.set.gov.py/de/ws/consultas/consulta-lote.wsdl"
        )

    def test_get_endpoint_rechaza_ambiente_desconocido(self) -> None:
        """L08."""
        with pytest.raises(ValueError, match="Ambiente SIFEN desconocido"):
            get_endpoint(99, "recep_de")

    def test_get_endpoint_rechaza_servicio_desconocido(self) -> None:
        """L09; el mensaje lista los servicios admitidos."""
        with pytest.raises(ValueError, match="Servicio SIFEN desconocido") as error:
            get_endpoint(PRODUCCION, "servicio_falso")
        assert "recep_de" in str(error.value)
        assert "cons_dte_async" in str(error.value)

    def test_get_endpoint_valida_ambiente_antes_que_servicio(self) -> None:
        with pytest.raises(ValueError, match="Ambiente SIFEN desconocido"):
            get_endpoint(99, "servicio_falso")

    @pytest.mark.parametrize("ambiente, servicio, url", URLS_OFICIALES)
    def test_tabla_completa_de_urls_por_ambiente(
        self, ambiente: int, servicio: str, url: str
    ) -> None:
        """N01."""
        assert get_endpoint(ambiente, servicio) == url

    def test_ambientes_comparten_el_mismo_conjunto_de_servicios(self) -> None:
        """N02."""
        assert set(ENDPOINTS) == {1, 2}
        for ambiente in ENDPOINTS:
            assert set(ENDPOINTS[ambiente]) == set(SERVICIOS)

    def test_get_endpoint_lee_la_tabla_en_cada_llamada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(ENDPOINTS[TEST], "cons_ruc", "https://otro.invalid/ruc")
        assert get_endpoint(TEST, "cons_ruc") == "https://otro.invalid/ruc"


# ---------------------------------------------------------------------------
# Importacion del paquete
# ---------------------------------------------------------------------------

_SCRIPT_IMPORTACION = (
    "import importlib, json, sys\n"
    "importlib.import_module(sys.argv[1])\n"
    "opcionales = ('requests', 'cryptography', 'signxml',"
    " 'xsdata.formats.dataclass.client')\n"
    "print(json.dumps([n for n in opcionales if n in sys.modules]))\n"
)

_SCRIPT_SIN_EXTRAS = """
import importlib.abc
import sys

BLOQUEADOS = frozenset({"lxml", "requests", "cryptography", "signxml"})


class Bloqueador(importlib.abc.MetaPathFinder):
    def find_spec(self, nombre, ruta=None, objetivo=None):
        if nombre.partition(".")[0] in BLOQUEADOS:
            raise ModuleNotFoundError(f"bloqueado: {nombre}", name=nombre)
        return None


sys.meta_path.insert(0, Bloqueador())
import kilasifen.engine
import kilasifen.engine.transmision
from kilasifen.engine import ConsultaSIFEN, TransmisionDE, TransmisionEvento
print("ok")
"""

MODULOS_DEL_CICLO = [
    "kilasifen.engine.transmision",
    "kilasifen.engine.transmision.base",
    "kilasifen.engine.transmision.de",
    "kilasifen.engine.sdk",
    "kilasifen.engine.sdk.errors",
    "kilasifen.engine.sdk.client",
    "kilasifen.infrastructure.sifen.event",
]


class TestImportacionPaquete:
    def test_paquete_transmision_exporta_api_publica(self) -> None:
        """L10."""
        from kilasifen.engine.transmision import (
            PRODUCCION as PRODUCCION_PAQUETE,
        )
        from kilasifen.engine.transmision import TEST as TEST_PAQUETE
        from kilasifen.engine.transmision import (
            ConsultaSIFEN as ConsultaPaquete,
        )
        from kilasifen.engine.transmision import (
            TransmisionDE as TransmisionDEPaquete,
        )
        from kilasifen.engine.transmision import (
            TransmisionEvento as TransmisionEventoPaquete,
        )

        assert PRODUCCION_PAQUETE == 1
        assert TEST_PAQUETE == 2
        assert ConsultaPaquete is not None
        assert TransmisionDEPaquete is not None
        assert TransmisionEventoPaquete is not None

    def test_modulo_config_exporta_constantes(self) -> None:
        """L11."""
        config = importlib.import_module("kilasifen.engine.transmision.config")
        assert callable(config.get_endpoint)
        assert isinstance(config.ENDPOINTS, dict)
        assert config.PRODUCCION == 1
        assert config.TEST == 2

    def test_modulo_base_expone_transmision_base(self) -> None:
        """L12."""
        modulo = importlib.import_module("kilasifen.engine.transmision.base")
        assert isinstance(modulo.TransmisionBase, type)

    def test_modulo_de_expone_transmision_de(self) -> None:
        """L13."""
        modulo = importlib.import_module("kilasifen.engine.transmision.de")
        assert isinstance(modulo.TransmisionDE, type)
        assert modulo.MAX_LOTE == 50
        assert callable(modulo._build_enviar_de_request_xml)

    def test_modulo_consulta_expone_consulta_sifen(self) -> None:
        """L14."""
        modulo = importlib.import_module("kilasifen.engine.transmision.consulta")
        assert isinstance(modulo.ConsultaSIFEN, type)

    def test_modulo_evento_expone_transmision_evento(self) -> None:
        """L15."""
        modulo = importlib.import_module("kilasifen.engine.transmision.evento")
        assert isinstance(modulo.TransmisionEvento, type)
        assert callable(modulo._generate_id)

    def test_all_del_paquete_es_exacto(self) -> None:
        """N03."""
        paquete = importlib.import_module("kilasifen.engine.transmision")
        assert set(paquete.__all__) == {
            "ENDPOINTS",
            "PRODUCCION",
            "TEST",
            "get_endpoint",
            "ConsultaSIFEN",
            "TransmisionDE",
            "TransmisionEvento",
        }

    @pytest.mark.parametrize("clase", [TransmisionDE, ConsultaSIFEN, TransmisionEvento])
    def test_clases_de_servicio_heredan_de_transmision_base(self, clase: type) -> None:
        """N04."""
        assert issubclass(clase, TransmisionBase)

    @pytest.mark.parametrize("modulo", MODULOS_DEL_CICLO)
    def test_importar_paquete_no_carga_dependencias_opcionales(
        self, modulo: str
    ) -> None:
        """N05: cada modulo del ciclo de importacion puede importarse primero en
        un interprete limpio, y el paquete no carga dependencias opcionales."""
        resultado = _ejecutar_python(_SCRIPT_IMPORTACION, modulo)
        assert resultado.returncode == 0, resultado.stderr
        if modulo == "kilasifen.engine.transmision":
            assert json.loads(resultado.stdout.strip().splitlines()[-1]) == []

    def test_importar_sin_dependencias_opcionales_instaladas(self) -> None:
        """La fachada y el paquete importan aunque falten lxml, requests,
        cryptography y signxml (import perezoso)."""
        resultado = _ejecutar_python(_SCRIPT_SIN_EXTRAS)
        assert resultado.returncode == 0, resultado.stderr
        assert resultado.stdout.strip().endswith("ok")

    def test_no_existe_paquete_legado(self) -> None:
        """Sin alias de compatibilidad con el nombre anterior del paquete."""
        assert find_spec("kilasifen.engine.transmissao") is None


# ---------------------------------------------------------------------------
# TransmisionBase: construccion, ciclo de vida, firma y serializacion
# ---------------------------------------------------------------------------


def _cerrar_con_error(credenciales: dict[str, Any]) -> TransmisionBase:
    instancia = TransmisionBase(**credenciales)

    def cerrar() -> None:
        raise RuntimeError("cierre fallido a proposito")

    instancia.close = cerrar  # type: ignore[method-assign]
    return instancia


def _a_medio_construir(_credenciales: dict[str, Any]) -> TransmisionBase:
    return object.__new__(TransmisionBase)


class TestTransmisionBase:
    @pytest.mark.parametrize(
        "clase", [TransmisionBase, TransmisionDE, ConsultaSIFEN, TransmisionEvento]
    )
    def test_valores_por_defecto_del_constructor(
        self, clase: type, credenciales_ficticias: dict[str, Any]
    ) -> None:
        """N06; las subclases heredan el constructor sin redefinirlo."""
        instancia = clase(**credenciales_ficticias)
        try:
            assert instancia.timeout == 30.0
            assert instancia.max_retries == 0
            assert instancia.retry_backoff == 0.2
        finally:
            instancia.close()
        if clase is not TransmisionBase:
            assert "__init__" not in vars(clase)

    def test_estado_inicial_es_perezoso(self, transmision_base: Any) -> None:
        assert transmision_base._cert_files is None
        assert transmision_base._signer is None
        assert transmision_base._transport is None
        assert transmision_base._clients == {}
        assert transmision_base._closed is False

    @pytest.mark.parametrize(
        "clase", [TransmisionBase, TransmisionDE, ConsultaSIFEN, TransmisionEvento]
    )
    def test_max_retries_negativo_se_rechaza(
        self, clase: type, credenciales_ficticias: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError):
            clase(**credenciales_ficticias, max_retries=-1)

    def test_constructor_no_valida_ambiente(
        self, credenciales_ficticias: dict[str, Any]
    ) -> None:
        credenciales = {**credenciales_ficticias, "ambiente": 99}
        with TransmisionBase(**credenciales) as transmision:
            with pytest.raises(ValueError, match="Ambiente SIFEN desconocido"):
                transmision._send_raw_xml("recep_de", b"<x/>")

    def test_firma_reutiliza_material_pkcs12(
        self, pfx_de_prueba: bytes, cargas_pkcs12: Registrador
    ) -> None:
        """L37; firmar no extrae los PEM del TLS mutuo."""
        xml = '<constancia Id="firma-prueba-37"><dato>uno</dato></constancia>'
        with TransmisionBase(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            primera = transmision._sign_xml(xml, "firma-prueba-37")
            segunda = transmision._sign_xml(xml, "firma-prueba-37")
            assert transmision._cert_files is None
        assert "SignatureValue" in primera
        assert segunda == primera
        assert cargas_pkcs12.veces == 1

    def test_firma_con_pkcs12_invalido_lanza_error_de_firma(
        self, transmision_base: Any
    ) -> None:
        pytest.importorskip("cryptography")
        with pytest.raises(SifenSignatureError):
            transmision_base._sign_xml("<a Id='x'/>", "x")

    def test_serializar_binding_a_texto_xml(self, transmision_base: Any) -> None:
        """L38."""
        texto = transmision_base._serialize(REnviConsRuc(dId=31415, dRUCCons="4567012"))
        assert isinstance(texto, str)
        assert texto.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
        assert "<ns0:rEnviConsRUC" in texto
        assert "4567012" in texto

    def test_parsear_texto_xml_a_binding(self, transmision_base: Any) -> None:
        """L39."""
        texto = transmision_base._serialize(REnviConsRuc(dId=31415, dRUCCons="4567012"))
        solicitud = transmision_base._parse(texto, REnviConsRuc)
        assert solicitud.dId == 31415
        assert solicitud.dRUCCons == "4567012"

    def test_cleanup_descarta_archivos_de_certificado(
        self, transmision_base: Any, tmp_path: Path
    ) -> None:
        """L40; ``cleanup`` cierra la instancia como ``close``."""
        transmision_base._cert_files = (
            str(tmp_path / "no-existe-cert.pem"),
            str(tmp_path / "no-existe-clave.pem"),
        )
        transmision_base.cleanup()
        assert transmision_base._cert_files is None
        assert transmision_base._closed is True

    def test_close_es_idempotente(
        self, transmision_base: Any, borrados: list[str]
    ) -> None:
        """L41."""
        transmision_base._cert_files = ("certificado-x.pem", "clave-x.pem")
        transmision_base.close()
        transmision_base.close()
        assert borrados == ["certificado-x.pem", "clave-x.pem"]
        assert transmision_base._cert_files is None

    def test_context_manager_libera_recursos_al_salir(
        self, credenciales_ficticias: dict[str, Any], borrados: list[str]
    ) -> None:
        """L42."""
        instancia = TransmisionBase(**credenciales_ficticias)
        with instancia as transmision:
            assert transmision is instancia
            transmision._cert_files = ("certificado-y.pem", "clave-y.pem")
        assert borrados == ["certificado-y.pem", "clave-y.pem"]
        assert instancia._cert_files is None
        assert instancia._closed is True

    def test_context_manager_no_suprime_excepciones(
        self, credenciales_ficticias: dict[str, Any]
    ) -> None:
        instancia = TransmisionBase(**credenciales_ficticias)
        with pytest.raises(KeyError):
            with instancia:
                raise KeyError("error del llamador")
        assert instancia._closed is True

    def test_operacion_tras_close_lanza_error_tipado(
        self, transmision_base: Any
    ) -> None:
        """L43."""
        transmision_base.close()
        with pytest.raises(SifenTransportClosedError):
            transmision_base._get_client("recep_de")

    def test_get_client_reutiliza_transporte_y_cliente(
        self, credenciales_ficticias: dict[str, Any], fabricas_falsas: FabricasFalsas
    ) -> None:
        """L48."""
        with TransmisionBase(
            **credenciales_ficticias, timeout=12, max_retries=4, retry_backoff=0.5
        ) as transmision:
            primero = transmision._get_client("recep_de")
            segundo = transmision._get_client("recep_de")

        assert primero is segundo
        assert primero.transport is fabricas_falsas.transportes[0]
        assert primero.parser is base._parser_de_respuestas()
        assert len(fabricas_falsas.llamadas_transporte) == 1
        args, kwargs = fabricas_falsas.llamadas_transporte[0]
        assert args == ("cert.pem", "key.pem")
        assert kwargs == {
            "timeout": 12,
            "max_retries": 4,
            "backoff_factor": 0.5,
            "key_password": CONTRASENA_CLAVE_FICTICIA,
            "reintentar_ambiguos": False,
        }
        configuracion = primero.config
        assert configuracion.input is REnviDe
        assert configuracion.output is RRetEnviDe
        assert configuracion.transport == cliente_xsdata.TransportTypes.SOAP
        assert configuracion.style == "document"
        assert configuracion.soap_action == ""
        assert configuracion.location == get_endpoint(TEST, "recep_de")

    def test_enter_sobre_instancia_cerrada_falla(self, transmision_base: Any) -> None:
        """N07."""
        transmision_base.close()
        with pytest.raises(SifenTransportClosedError):
            with transmision_base:
                pass

    @pytest.mark.parametrize(
        "operacion",
        [
            pytest.param(lambda t: t._get_transport(), id="get_transport"),
            pytest.param(lambda t: t._get_cert_files(), id="get_cert_files"),
            pytest.param(lambda t: t._get_signer(), id="get_signer"),
            pytest.param(lambda t: t._sign_xml("<a Id='x'/>", "x"), id="sign_xml"),
            pytest.param(
                lambda t: t._send_raw_xml("cons_ruc", b"<a/>"), id="send_raw_xml"
            ),
        ],
    )
    def test_operaciones_internas_tras_close_fallan(
        self, transmision_base: Any, operacion: Callable[[Any], Any]
    ) -> None:
        """N08."""
        transmision_base.close()
        with pytest.raises(SifenTransportClosedError) as error:
            operacion(transmision_base)
        assert isinstance(error.value, SifenTransportError)

    def test_send_raw_xml_valida_servicio_antes_del_cierre(
        self, transmision_base: Any
    ) -> None:
        transmision_base.close()
        with pytest.raises(ValueError, match="Servicio SIFEN desconocido"):
            transmision_base._send_raw_xml("servicio_falso", b"<a/>")

    def test_cliente_cacheado_tras_close_falla(
        self, transmision_base: Any, fabricas_falsas: FabricasFalsas
    ) -> None:
        """N08 (cliente ya cacheado antes del cierre).

        El cierre se verifica antes de mirar la cache: ni siquiera un cliente
        que siguiera en la cache se entrega tras ``close()``.
        """
        cliente = transmision_base._get_client("cons_ruc")
        transmision_base.close()
        with pytest.raises(SifenTransportClosedError):
            transmision_base._get_client("cons_ruc")
        transmision_base._clients["cons_ruc"] = cliente
        with pytest.raises(SifenTransportClosedError):
            transmision_base._get_client("cons_ruc")

    def test_close_cierra_transporte_y_olvida_clientes(
        self, transmision_base: Any, fabricas_falsas: FabricasFalsas
    ) -> None:
        """N09; tambien suelta el firmador memorizado."""
        transmision_base._get_client("cons_de")
        transmision_base._signer = object()
        transmision_base.close()
        assert fabricas_falsas.transportes[0].cierres == 1
        assert transmision_base._transport is None
        assert transmision_base._clients == {}
        assert transmision_base._signer is None

    def test_cleanup_y_del_delegan_dinamicamente(
        self, credenciales_ficticias: dict[str, Any]
    ) -> None:
        """``cleanup`` llama a ``self.close`` y ``__del__`` a ``self.cleanup``."""
        instancia = TransmisionBase(**credenciales_ficticias)
        cierre = Registrador()
        instancia.close = cierre  # type: ignore[method-assign]
        instancia.cleanup()
        assert cierre.veces == 1

        limpieza = Registrador()
        instancia.cleanup = limpieza  # type: ignore[method-assign]
        instancia.__del__()
        assert limpieza.veces == 1

        del instancia.cleanup
        del instancia.close
        instancia.close()
        assert instancia._closed is True

    def test_close_tolera_fallo_al_cerrar_transporte(
        self,
        transmision_base: Any,
        fabricas_falsas: FabricasFalsas,
        borrados: list[str],
    ) -> None:
        """N10; aun asi se borran los PEM."""
        transmision_base._get_client("cons_de")
        fabricas_falsas.transportes[0].error_al_cerrar = RuntimeError("sin cierre")
        transmision_base._cert_files = ("certificado-z.pem", "clave-z.pem")
        transmision_base.close()
        assert transmision_base._cert_files is None
        assert borrados == ["certificado-z.pem", "clave-z.pem"]

    def test_cleanup_transport_permite_reconectar(
        self, transmision_base: Any, fabricas_falsas: FabricasFalsas
    ) -> None:
        """N11."""
        primero = transmision_base._get_client("cons_ruc")
        transmision_base._cleanup_transport()
        segundo = transmision_base._get_client("cons_ruc")
        assert len(fabricas_falsas.llamadas_transporte) == 2
        assert segundo is not primero
        assert fabricas_falsas.transportes[0].cierres == 1
        assert transmision_base._closed is False

    def test_cleanup_transport_conserva_los_pem(
        self, transmision_base: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La reconexion no vuelve a extraer el PKCS#12."""
        llamadas: list[tuple[Any, ...]] = []

        def crear_transporte(*args: Any, **kwargs: Any) -> TransporteFalso:
            llamadas.append(args)
            return TransporteFalso()

        monkeypatch.setattr(base, "_create_transport", crear_transporte)
        rutas = ("pem-previo-cert.pem", "pem-previo-clave.pem")
        transmision_base._cert_files = rutas

        transmision_base._get_transport()
        transmision_base._cleanup_transport()
        transmision_base._get_transport()

        assert transmision_base._cert_files is rutas
        assert llamadas == [rutas, rutas]

    def test_transporte_captura_la_configuracion_al_crearse(
        self, transmision_base: Any, fabricas_falsas: FabricasFalsas
    ) -> None:
        primero = transmision_base._get_transport()
        transmision_base.timeout = 7.5
        transmision_base.max_retries = 3
        transmision_base.retry_backoff = 0.05
        assert transmision_base._get_transport() is primero
        assert len(fabricas_falsas.llamadas_transporte) == 1

        transmision_base._cleanup_transport()
        transmision_base._get_transport()
        _args, kwargs = fabricas_falsas.llamadas_transporte[1]
        assert kwargs == {
            "timeout": 7.5,
            "max_retries": 3,
            "backoff_factor": 0.05,
            "key_password": CONTRASENA_CLAVE_FICTICIA,
            "reintentar_ambiguos": False,
        }

    def test_servicios_distintos_comparten_transporte(
        self, transmision_base: Any, fabricas_falsas: FabricasFalsas
    ) -> None:
        """N12."""
        ruc = transmision_base._get_client("cons_ruc")
        documento = transmision_base._get_client("cons_de")
        assert ruc is not documento
        assert ruc.transport is documento.transport
        assert len(fabricas_falsas.llamadas_transporte) == 1

    @pytest.mark.parametrize("servicio, entrada, salida", MODELOS_POR_SERVICIO)
    def test_get_client_configura_modelos_por_servicio(
        self,
        transmision_base: Any,
        fabricas_falsas: FabricasFalsas,
        servicio: str,
        entrada: type,
        salida: type,
    ) -> None:
        """N13."""
        configuracion = transmision_base._get_client(servicio).config
        assert configuracion.input is entrada
        assert configuracion.output is salida
        assert configuracion.location == get_endpoint(TEST, servicio)
        assert configuracion.soap_action == ""

    @pytest.mark.parametrize("servicio, entrada, salida", MODELOS_POR_SERVICIO)
    def test_modelos_por_servicio_tabla_completa(
        self, servicio: str, entrada: type, salida: type
    ) -> None:
        assert base._get_service_models(servicio) == (entrada, salida)

    def test_modelos_de_servicio_desconocido(self) -> None:
        with pytest.raises(ValueError, match="sin modelos SOAP"):
            base._get_service_models("servicio_falso")

    def test_get_client_rechaza_servicio_desconocido(
        self, transmision_base: Any, fabricas_falsas: FabricasFalsas
    ) -> None:
        """N14."""
        with pytest.raises(ValueError):
            transmision_base._get_client("servicio_falso")
        assert fabricas_falsas.llamadas_transporte == []
        assert fabricas_falsas.lecturas_certificado == 0

    def test_archivos_de_certificado_desde_pkcs12_real(
        self, pfx_de_prueba: bytes, cargas_pkcs12: Registrador
    ) -> None:
        """N15."""
        with TransmisionBase(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            rutas = transmision._get_cert_files()
            ruta_certificado, ruta_clave = rutas
            assert Path(ruta_certificado).is_file()
            assert Path(ruta_clave).is_file()
            assert ruta_certificado.endswith(".pem")
            assert ruta_clave.endswith(".pem")
            certificado = Path(ruta_certificado).read_text(encoding="ascii")
            clave = Path(ruta_clave).read_text(encoding="ascii")
            assert "-----BEGIN CERTIFICATE-----" in certificado
            assert clave.startswith("-----BEGIN ENCRYPTED PRIVATE KEY-----")
            assert transmision._get_cert_files() is rutas
            assert cargas_pkcs12.veces == 1
        assert not Path(ruta_certificado).exists()
        assert not Path(ruta_clave).exists()
        assert transmision._key_password is None

        with TransmisionBase(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA.encode("ascii"),
        ) as con_bytes:
            rutas_bytes = con_bytes._get_cert_files()
            assert all(Path(ruta).is_file() for ruta in rutas_bytes)
        assert not any(Path(ruta).exists() for ruta in rutas_bytes)

    def test_pkcs12_invalido_no_es_error_de_transporte(
        self, transmision_base: Any
    ) -> None:
        pytest.importorskip("cryptography")
        with pytest.raises(ValueError) as error:
            transmision_base._get_cert_files()
        assert not isinstance(error.value, SifenTransportError)
        assert transmision_base._cert_files is None

    @pytest.mark.skipif(os.name == "nt", reason="permisos POSIX")
    def test_pem_con_permisos_restrictivos(self, pfx_de_prueba: bytes) -> None:
        with TransmisionBase(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            for ruta in transmision._get_cert_files():
                assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600

    def test_clave_en_disco_solo_se_lee_con_la_contrasena_en_memoria(
        self, pfx_de_prueba: bytes
    ) -> None:
        """La clave PEM queda cifrada; la contrasena no se escribe en disco."""
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key,
            pkcs12,
        )

        original, _certificado, _cadena = pkcs12.load_key_and_certificates(
            pfx_de_prueba, CONTRASENA_CERTIFICADO_PRUEBA.encode("ascii")
        )
        with TransmisionBase(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            ruta_certificado, ruta_clave = transmision._get_cert_files()
            contrasena = transmision._key_password
            clave_pem = Path(ruta_clave).read_bytes()

            assert isinstance(contrasena, bytes)
            assert len(contrasena) >= 32
            assert contrasena not in clave_pem
            assert contrasena not in Path(ruta_certificado).read_bytes()
            with pytest.raises(TypeError):
                load_pem_private_key(clave_pem, password=None)
            with pytest.raises(ValueError):
                load_pem_private_key(clave_pem, password=b"contrasena-incorrecta")
            descifrada = load_pem_private_key(clave_pem, password=contrasena)
            assert descifrada.private_numbers() == original.private_numbers()

            contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            contexto.load_cert_chain(ruta_certificado, ruta_clave, password=contrasena)

    def test_cada_instancia_cifra_la_clave_con_otra_contrasena(
        self, pfx_de_prueba: bytes
    ) -> None:
        contrasenas = []
        for _ in range(2):
            with TransmisionBase(
                ambiente=TEST,
                pkcs12_data=pfx_de_prueba,
                pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
            ) as transmision:
                transmision._get_cert_files()
                contrasenas.append(transmision._key_password)
        assert contrasenas[0] != contrasenas[1]

    def test_transporte_recibe_la_contrasena_de_la_clave(
        self, pfx_de_prueba: bytes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def crear_transporte(*args: Any, **kwargs: Any) -> TransporteFalso:
            llamadas.append((args, kwargs))
            return TransporteFalso()

        monkeypatch.setattr(base, "_create_transport", crear_transporte)
        with TransmisionBase(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            transmision._get_transport()
            ((args, kwargs),) = llamadas
            assert args == transmision._cert_files
            assert kwargs["key_password"] == transmision._key_password

    @pytest.mark.parametrize(
        "fabricar",
        [
            pytest.param(_cerrar_con_error, id="close_que_falla"),
            pytest.param(_a_medio_construir, id="sin_init"),
        ],
    )
    def test_del_no_propaga_excepciones(
        self,
        fabricar: Callable[[dict[str, Any]], TransmisionBase],
        credenciales_ficticias: dict[str, Any],
    ) -> None:
        """N16."""
        instancia = fabricar(credenciales_ficticias)
        instancia.__del__()

    def test_instancias_con_mismo_pkcs12_comparten_firmador(
        self, pfx_de_prueba: bytes, cargas_pkcs12: Registrador
    ) -> None:
        """N17."""
        xml = '<aviso Id="firma-compartida-17"><dato>dos</dato></aviso>'
        for _ in range(2):
            with TransmisionBase(
                ambiente=TEST,
                pkcs12_data=pfx_de_prueba,
                pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
            ) as transmision:
                assert "SignatureValue" in transmision._sign_xml(
                    xml, "firma-compartida-17"
                )
        assert cargas_pkcs12.veces == 1

    def test_validaciones_preceden_al_estado_cerrado(
        self, consulta: Any, transmision_de: Any
    ) -> None:
        consulta.close()
        transmision_de.close()
        with pytest.raises(ValueError, match="44 digitos"):
            consulta.consultar_de("123")
        with pytest.raises(ValueError, match="de 5 a 8 caracteres"):
            consulta.consultar_ruc("12")
        with pytest.raises(ValueError, match="al menos un documento"):
            transmision_de.enviar_lote([])
        with pytest.raises(ValueError, match="como maximo 50"):
            transmision_de.enviar_lote([object()] * 51)
        with pytest.raises(SifenTransportClosedError):
            consulta.consultar_de(_cdc_ficticio(26))


# ---------------------------------------------------------------------------
# Transporte HTTP (RequestsTransport)
# ---------------------------------------------------------------------------

URL_PRUEBA = "https://example.invalid/ws"


class TestTransporteSoap:
    def test_transporte_reintenta_timeout_y_luego_responde(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """L44; en el camino de exito no se lee ``status_code``."""
        transporte_http = transporte(max_retries=1)
        sesion = sesion_programada(
            transporte_http,
            requests.exceptions.Timeout("sin respuesta a tiempo"),
            respuesta_http(b"<ok />", status_code=None),
        )
        resultado = transporte_http.post("https://example.invalid", b"<xml />")
        assert resultado == b"<ok />"
        assert len(sesion.llamadas) == 2
        primero, segundo = sesion.llamadas
        # El sobre se arma una vez y se reutiliza tal cual en el reintento.
        assert segundo.data == primero.data
        assert segundo.headers == primero.headers
        assert segundo.timeout == primero.timeout == 0.01

    def test_transporte_no_reintenta_http_4xx(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """L45."""
        transporte_http = transporte(max_retries=3)
        sesion = sesion_programada(transporte_http, respuesta_http(b"", 400))
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert isinstance(error.value.__cause__, requests.exceptions.HTTPError)
        assert len(sesion.llamadas) == 1

    def test_transporte_devuelve_body_soap_de_http_400(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """L46."""
        transporte_http = transporte(max_retries=0)
        sobre = (
            f'<env:Envelope xmlns:env="{NS_SOAP12}"><env:Body>'
            "<rRetEnviDe>rechazado</rRetEnviDe></env:Body></env:Envelope>"
        ).encode("utf-8")
        sesion_programada(transporte_http, respuesta_http(sobre, 400))
        resultado = transporte_http.post(URL_PRUEBA, b"<xml />")
        assert resultado == b"<rRetEnviDe>rechazado</rRetEnviDe>"

    def test_transporte_envuelve_en_soap12_y_extrae_body(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """L47."""
        transporte_http = transporte(max_retries=0)
        sobre_respuesta = (
            f'<soap:Envelope xmlns:soap="{NS_SOAP11}"><soap:Body>'
            "<rRespuesta>ok</rRespuesta></soap:Body></soap:Envelope>"
        ).encode("utf-8")
        sesion = sesion_programada(transporte_http, respuesta_http(sobre_respuesta))
        payload = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b"<rEnviConsRUC><dId>2718</dId></rEnviConsRUC>"
        )

        resultado = transporte_http.post(URL_PRUEBA, payload)

        enviado = sesion.llamadas[0]
        assert b"<soap:Envelope" in enviado.data
        assert NS_SOAP12.encode("ascii") in enviado.data
        assert b"<soap:Body>" in enviado.data
        assert b"<rEnviConsRUC>" in enviado.data
        assert enviado.data.count(b"<?xml") == 1
        assert enviado.headers["Content-Type"] == TIPO_CONTENIDO_SOAP12
        assert "content-type" not in enviado.headers
        assert resultado == b"<rRespuesta>ok</rRespuesta>"

    @pytest.mark.parametrize(
        "contenido",
        [b"", b"Servicio temporalmente no disponible"],
        ids=["vacio", "texto"],
    )
    def test_transporte_reintenta_5xx_sin_cuerpo_y_agota(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
        contenido: bytes,
    ) -> None:
        """N18."""
        transporte_http = transporte(max_retries=1)
        sesion = sesion_programada(transporte_http, respuesta_http(contenido, 503))
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert not isinstance(error.value, SifenTimeoutError)
        assert isinstance(error.value.__cause__, requests.exceptions.HTTPError)
        assert len(sesion.llamadas) == 2

    def test_transporte_devuelve_cuerpo_xml_de_http_5xx_sin_reintentar(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """N19."""
        transporte_http = transporte(max_retries=3)
        falla = (
            f'<env:Envelope xmlns:env="{NS_SOAP12}"><env:Body><env:Fault>'
            "<env:Code><env:Value>env:Receiver</env:Value></env:Code>"
            "<env:Reason><env:Text>falla interna del servicio</env:Text></env:Reason>"
            "</env:Fault></env:Body></env:Envelope>"
        ).encode("utf-8")
        sesion = sesion_programada(transporte_http, respuesta_http(falla, 500))
        resultado = transporte_http.post(URL_PRUEBA, b"<xml />")
        assert ET.fromstring(resultado).tag == f"{{{NS_SOAP12}}}Fault"
        assert len(sesion.llamadas) == 1

    def test_transporte_4xx_con_cuerpo_no_xml_falla_sin_reintentar(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """N20."""
        transporte_http = transporte(max_retries=3)
        sesion = sesion_programada(
            transporte_http, respuesta_http(b"Solicitud invalida: falta dId", 400)
        )
        with pytest.raises(SifenTransportError):
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert len(sesion.llamadas) == 1

    @pytest.mark.parametrize(
        "tipo",
        [requests.exceptions.ConnectionError, requests.exceptions.SSLError],
        ids=["ConnectionError", "SSLError"],
    )
    def test_transporte_reintenta_errores_de_conexion(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        esperas: list[float],
        tipo: type[Exception],
    ) -> None:
        """N21."""
        transporte_http = transporte(max_retries=2, backoff_factor=0.1)
        falla = tipo("conexion rechazada")
        sesion = sesion_programada(transporte_http, falla)
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert len(sesion.llamadas) == 3
        assert esperas == [0.1, 0.2]
        assert not isinstance(error.value, SifenTimeoutError)
        assert error.value.__cause__ is falla

    @pytest.mark.parametrize(
        "tipo, error_esperado",
        [
            (requests.exceptions.Timeout, SifenTimeoutError),
            (requests.exceptions.ReadTimeout, SifenTimeoutError),
            # Agotar el tiempo al conectar prueba que nada se envio.
            (requests.exceptions.ConnectTimeout, SifenRequestNotSentError),
        ],
        ids=["Timeout", "ReadTimeout", "ConnectTimeout"],
    )
    def test_transporte_timeout_agotado_lanza_sifen_timeout(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        tipo: type[Exception],
        error_esperado: type[Exception],
    ) -> None:
        """N22."""
        transporte_http = transporte(max_retries=1)
        sesion = sesion_programada(transporte_http, tipo("sin respuesta"))
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert type(error.value) is error_esperado
        assert isinstance(error.value.__cause__, tipo)
        assert len(sesion.llamadas) == 2

    @pytest.mark.parametrize(
        "falla",
        [
            pytest.param(requests.exceptions.InvalidURL("url mal formada"), id="url"),
            pytest.param(
                requests.exceptions.ContentDecodingError("gzip roto"), id="decodif"
            ),
        ],
    )
    def test_transporte_no_reintenta_otras_request_exception(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        falla: Exception,
    ) -> None:
        """N23."""
        transporte_http = transporte(max_retries=3)
        sesion = sesion_programada(transporte_http, falla)
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert not isinstance(error.value, SifenTimeoutError)
        assert error.value.__cause__ is falla
        assert len(sesion.llamadas) == 1

    def test_transporte_sin_backoff_no_duerme(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
        esperas: list[float],
    ) -> None:
        """N24."""
        transporte_http = transporte(max_retries=1, backoff_factor=0.0)
        sesion_programada(
            transporte_http,
            requests.exceptions.Timeout("lento"),
            respuesta_http(b"<ok/>"),
        )
        transporte_http.post(URL_PRUEBA, b"<xml />")
        assert esperas == []

    def test_transporte_backoff_exponencial(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        esperas: list[float],
    ) -> None:
        transporte_http = transporte(max_retries=3, backoff_factor=0.5)
        sesion_programada(transporte_http, requests.exceptions.Timeout("lento"))
        with pytest.raises(SifenTimeoutError):
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert esperas == [0.5, 1.0, 2.0]

    def test_transporte_valores_por_defecto(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        esperas: list[float],
    ) -> None:
        """N25."""
        transporte_http = transporte(rutas=("c.pem", "k.pem"), por_defecto=True)
        assert isinstance(transporte_http._session, requests.Session)
        assert transporte_http._session.cert is None
        assert transporte_http._session.verify is True
        adaptador = transporte_http._session.get_adapter(URL_PRUEBA)
        assert isinstance(adaptador, conexion.AdaptadorTlsMutuo)
        assert adaptador._ruta_certificado == "c.pem"
        assert adaptador._ruta_clave == "k.pem"
        assert adaptador._contrasena_clave is None

        sesion = sesion_programada(
            transporte_http,
            requests.exceptions.ConnectTimeout("sin conexion"),
            requests.exceptions.ConnectTimeout("sin conexion"),
            requests.exceptions.Timeout("lento"),
        )
        with pytest.raises(SifenTimeoutError):
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert [llamada.timeout for llamada in sesion.llamadas] == [30.0] * 3
        assert esperas == [0.2, 0.4]

    def test_transporte_por_defecto_no_reintenta_fallos_ambiguos(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        esperas: list[float],
    ) -> None:
        """Sin ``reintentar_ambiguos`` un timeout de lectura sale al primer
        intento, aunque queden reintentos."""
        transporte_http = transporte(por_defecto=True)
        sesion = sesion_programada(
            transporte_http, requests.exceptions.Timeout("lento")
        )
        with pytest.raises(SifenTimeoutError):
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert len(sesion.llamadas) == 1
        assert esperas == []

    def test_transporte_crea_sesion_nueva_de_tipo_exacto(
        self, transporte: Callable[..., Any]
    ) -> None:
        uno = transporte()
        otro = transporte()
        assert type(uno._session) is requests.Session
        assert type(otro._session) is requests.Session
        assert uno._session is not otro._session

    @pytest.mark.parametrize(
        "contenido",
        [
            pytest.param(b"texto plano sin marcado", id="no_xml"),
            pytest.param(b'<rX xmlns="urn:otro"><b/></rX>', id="xml_sin_sobre"),
            pytest.param(
                f'<e:Envelope xmlns:e="{NS_SOAP12}"><e:Body/></e:Envelope>'.encode(),
                id="body_vacio",
            ),
        ],
    )
    def test_transporte_respuestas_no_soap_se_devuelven_intactas(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
        contenido: bytes,
    ) -> None:
        """N26."""
        transporte_http = transporte()
        sesion_programada(transporte_http, respuesta_http(contenido))
        assert transporte_http.post(URL_PRUEBA, b"<xml />") == contenido

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(
                "  <soap:Envelope xmlns:soap='urn:propio'><soap:Body><x/>"
                "</soap:Body></soap:Envelope>\n",
                id="soap",
            ),
            pytest.param(
                f"\n\t<soapenv:Envelope xmlns:soapenv='{NS_SOAP11}'>"
                "<soapenv:Body><y/></soapenv:Body></soapenv:Envelope>  ",
                id="soapenv",
            ),
        ],
    )
    def test_transporte_no_reenvuelve_un_sobre_existente(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
        payload: str,
    ) -> None:
        """N27."""
        transporte_http = transporte()
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))
        transporte_http.post(URL_PRUEBA, payload)
        assert sesion.llamadas[0].data == payload.strip().encode("utf-8")

    def test_transporte_normaliza_cabeceras_y_conserva_extras(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """N28."""
        transporte_http = transporte(timeout=0.01)
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))
        transporte_http.post(
            URL_PRUEBA,
            b"<xml />",
            headers={"content-type": "text/xml", "SOAPAction": "urn:x"},
        )
        enviado = sesion.llamadas[0]
        assert enviado.url == URL_PRUEBA
        assert enviado.headers == {
            "Content-Type": TIPO_CONTENIDO_SOAP12,
            "SOAPAction": "urn:x",
        }
        assert enviado.timeout == 0.01

    def test_transporte_solo_normaliza_las_dos_grafias_de_content_type(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        transporte_http = transporte()
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))
        transporte_http.post(
            URL_PRUEBA,
            b"<xml />",
            headers={"SOAPAction": "urn:y", "Content-type": "a", "content-type": "b"},
        )
        assert sesion.llamadas[0].headers == {
            "SOAPAction": "urn:y",
            "Content-type": "a",
            "Content-Type": TIPO_CONTENIDO_SOAP12,
        }

    def test_transporte_close_cierra_la_sesion(
        self, transporte: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N29."""
        transporte_http = transporte()
        cierre = Registrador()
        monkeypatch.setattr(transporte_http._session, "close", cierre)
        transporte_http.close()
        assert cierre.veces == 1

    def test_transporte_acepta_payload_str(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """N30."""
        transporte_http = transporte()
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))
        transporte_http.post(URL_PRUEBA, "<consulta><dId>99</dId></consulta>")
        enviado = sesion.llamadas[0].data
        assert isinstance(enviado, bytes)
        assert enviado.startswith(b"<?xml")
        assert b"<soap:Header/>" in enviado
        assert b"<soap:Body><consulta><dId>99</dId></consulta></soap:Body>" in enviado

    def test_transporte_payload_no_utf8_no_envia(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        transporte_http = transporte(max_retries=2)
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))
        with pytest.raises(UnicodeDecodeError):
            transporte_http.post(URL_PRUEBA, b"<r>\xff</r>")
        assert sesion.llamadas == []

    def test_transporte_con_reintentos_negativos_no_envia(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        transporte_http = transporte(max_retries=-1)
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert error.value.__cause__ is None
        assert sesion.llamadas == []

    @pytest.mark.parametrize(
        "con_respuesta_adjunta", [False, True], ids=["sin_response", "sin_estado"]
    )
    def test_transporte_http_error_sin_respuesta_se_reintenta(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        con_respuesta_adjunta: bool,
    ) -> None:
        """N68."""
        transporte_http = transporte(max_retries=1, backoff_factor=0.0)
        sesion = sesion_programada(
            transporte_http, RespuestaSinEstado(con_respuesta_adjunta)
        )
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert not isinstance(error.value, SifenTimeoutError)
        assert isinstance(error.value.__cause__, requests.exceptions.HTTPError)
        assert len(sesion.llamadas) == 2

    @pytest.mark.parametrize(
        "ns_sobre", [NS_SOAP12, NS_SOAP11], ids=["soap12", "soap11"]
    )
    def test_transporte_extrae_body_con_namespace_declarado_en_el_sobre(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
        ns_sobre: str,
    ) -> None:
        """N70."""
        sobre = (
            f'<e:Envelope xmlns:e="{ns_sobre}" xmlns:sf="{NS_SIFEN}">'
            "<e:Header><sf:dTraza>traza-70</sf:dTraza></e:Header>"
            "<e:Body><sf:rResEnviConsRUC><sf:dCodRes>0502</sf:dCodRes>"
            "<sf:dMsgRes>RUC encontrado</sf:dMsgRes></sf:rResEnviConsRUC>"
            "</e:Body></e:Envelope>"
        ).encode("utf-8")
        transporte_http = transporte()
        sesion_programada(transporte_http, respuesta_http(sobre))

        resultado = transporte_http.post(URL_PRUEBA, b"<xml />")

        for fragmento in (b"<?xml", b"Envelope", b"Body", b"Header"):
            assert fragmento not in resultado
        raiz = ET.fromstring(resultado)
        assert raiz.tag == f"{{{NS_SIFEN}}}rResEnviConsRUC"
        assert raiz.find(f"{{{NS_SIFEN}}}dCodRes").text == "0502"

    @pytest.mark.parametrize("como_bytes", [False, True], ids=["str", "bytes"])
    def test_transporte_sobre_exacto_y_payload_textual(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
        como_bytes: bool,
    ) -> None:
        """N71."""
        elemento = (
            "<k:aviso xmlns:k='urn:kilasifen:aviso' k:canal='mostrador central'>"
            "  Pago en Encarnaci\u00f3n con \u00f1  </k:aviso>"
        )
        payload = (
            "  \t<?xml version='1.0' encoding='UTF-8'?>\n   " + elemento + " \n\t "
        )
        transporte_http = transporte()
        sesion = sesion_programada(transporte_http, respuesta_http(b"<ok/>"))

        transporte_http.post(
            URL_PRUEBA, payload.encode("utf-8") if como_bytes else payload
        )

        assert sesion.llamadas[0].data == (
            APERTURA_SOBRE + elemento.encode("utf-8") + CIERRE_SOBRE
        )

    def test_transporte_excepcion_ajena_a_requests_se_propaga(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
    ) -> None:
        """N74."""
        transporte_http = transporte(max_retries=3)
        falla = RuntimeError("falla propia del entorno")
        sesion = sesion_programada(transporte_http, falla)
        with pytest.raises(RuntimeError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert error.value is falla
        assert len(sesion.llamadas) == 1

    @pytest.mark.parametrize(
        "falla, reintentos, tipo_error",
        [
            pytest.param(
                lambda url: requests.exceptions.Timeout(f"lento hacia {url}"),
                1,
                SifenTimeoutError,
                id="timeout",
            ),
            pytest.param(
                lambda url: RespuestaHttpFalsa(b"", 400),
                0,
                SifenTransportError,
                id="http_400",
            ),
            pytest.param(
                lambda url: requests.exceptions.ConnectionError(f"sin ruta a {url}"),
                1,
                SifenTransportError,
                id="conexion",
            ),
            pytest.param(
                lambda url: RespuestaHttpFalsa(b"", 503),
                1,
                SifenTransportError,
                id="http_503",
            ),
        ],
    )
    def test_transporte_mensajes_de_error_sin_datos_sensibles(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        falla: Callable[[str], Any],
        reintentos: int,
        tipo_error: type[Exception],
    ) -> None:
        """N75."""
        marca_url = "marca-url-91c2"
        marca_payload = "MARCA-PAYLOAD-7F3A"
        url = f"https://{marca_url}.invalid/ws"
        transporte_http = transporte(max_retries=reintentos)
        sesion_programada(transporte_http, falla(url))

        with pytest.raises(tipo_error) as error:
            transporte_http.post(url, f"<consulta>{marca_payload}</consulta>")

        texto = str(error.value)
        assert texto
        assert marca_url not in texto
        assert marca_payload not in texto

    def test_transporte_4xx_con_xml_sin_sobre_se_devuelve(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        """N76."""
        transporte_http = transporte(max_retries=3)
        contenido = b"<rechazo><motivo>dId ausente</motivo></rechazo>"
        sesion = sesion_programada(transporte_http, respuesta_http(contenido, 400))
        assert transporte_http.post(URL_PRUEBA, b"<xml />") == contenido
        assert len(sesion.llamadas) == 1


# ---------------------------------------------------------------------------
# Sesion HTTPS con TLS mutuo (``conexion``)
# ---------------------------------------------------------------------------


@pytest.fixture
def pem_de_prueba(pfx_de_prueba: bytes) -> Iterator[tuple[str, str, bytes]]:
    """``(certificado, clave cifrada, contrasena)`` extraidos del PKCS#12."""
    with TransmisionBase(
        ambiente=TEST,
        pkcs12_data=pfx_de_prueba,
        pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
    ) as transmision:
        ruta_certificado, ruta_clave = transmision._get_cert_files()
        yield ruta_certificado, ruta_clave, transmision._key_password


class TestConexionTlsMutuo:
    def test_sesion_verifica_al_servidor_con_contexto_propio(self) -> None:
        sesion = conexion.crear_sesion_tls_mutuo("c.pem", "k.pem", b"clave")
        try:
            assert sesion.cert is None
            assert sesion.verify is True
            adaptador = sesion.get_adapter(get_endpoint(TEST, "recep_de"))
            assert isinstance(adaptador, conexion.AdaptadorTlsMutuo)
            contexto = adaptador.contexto_tls
            assert contexto.verify_mode == ssl.CERT_REQUIRED
            assert contexto.check_hostname is True
            assert contexto.get_ca_certs()
            pool = adaptador.poolmanager.connection_pool_kw
            assert pool["ssl_context"] is contexto
            assert sesion.get_adapter("http://example.invalid") is not adaptador
        finally:
            sesion.close()

    def test_proxy_usa_el_mismo_contexto(self) -> None:
        adaptador = conexion.AdaptadorTlsMutuo("c.pem", "k.pem", None)
        try:
            gestor = adaptador.proxy_manager_for("http://proxy.invalid:3128")
            assert gestor.connection_pool_kw["ssl_context"] is adaptador.contexto_tls
        finally:
            adaptador.close()

    def test_crear_el_adaptador_no_lee_archivos(self) -> None:
        adaptador = conexion.AdaptadorTlsMutuo(
            "no-existe-cert.pem", "no-existe-clave.pem", b"clave"
        )
        adaptador.close()

    def test_carga_el_certificado_una_sola_vez_en_el_primer_envio(
        self,
        pem_de_prueba: tuple[str, str, bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ruta_certificado, ruta_clave, contrasena = pem_de_prueba
        envios = Registrador("respuesta-ficticia")
        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", envios)
        adaptador = conexion.AdaptadorTlsMutuo(ruta_certificado, ruta_clave, contrasena)
        cargas = Registrador(efecto=adaptador.contexto_tls.load_cert_chain)
        adaptador.contexto_tls.load_cert_chain = cargas

        assert adaptador.send("primera", timeout=3) == "respuesta-ficticia"
        assert adaptador.send("segunda") == "respuesta-ficticia"

        assert cargas.llamadas == [
            ((ruta_certificado, ruta_clave), {"password": contrasena})
        ]
        # ``Registrador`` no es descriptor: como atributo de clase no recibe self.
        assert envios.llamadas == [(("primera",), {"timeout": 3}), (("segunda",), {})]

    def test_contrasena_incorrecta_falla_antes_de_conectar(
        self,
        pem_de_prueba: tuple[str, str, bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ruta_certificado, ruta_clave, _contrasena = pem_de_prueba
        envios = Registrador()
        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", envios)
        adaptador = conexion.AdaptadorTlsMutuo(
            ruta_certificado, ruta_clave, b"contrasena-incorrecta"
        )
        with pytest.raises(ssl.SSLError):
            adaptador.send("solicitud")
        assert envios.veces == 0


# ---------------------------------------------------------------------------
# Fallos en que la solicitud no llego al SIFEN
# ---------------------------------------------------------------------------

URL_RECEPCION_PRUEBA = get_endpoint(TEST, "recep_de")


def _por_requests(tipo: type[Exception], razon: BaseException) -> Exception:
    """Envuelve ``razon`` como lo hace ``HTTPAdapter.send`` con un MaxRetryError."""
    return tipo(urllib3_exc.MaxRetryError(None, URL_RECEPCION_PRUEBA, reason=razon))


def _timeout_mientras_se_maneja_un_fallo_de_conexion() -> Exception:
    """ReadTimeout cuyo ``__context__`` es un fallo de conexion previo y ajeno."""
    try:
        raise urllib3_exc.NewConnectionError(None, "fallo de conexion anterior")
    except urllib3_exc.NewConnectionError:
        try:
            raise requests.exceptions.ReadTimeout("lectura agotada")
        except requests.exceptions.ReadTimeout as exc:
            return exc


def _ssl_error_tras_el_handshake() -> Exception:
    return _por_requests(
        requests.exceptions.SSLError,
        urllib3_exc.SSLError(ssl.SSLError(1, "decryption failed or bad record mac")),
    )


FALLOS_NO_ENVIADOS = [
    pytest.param(
        lambda: _por_requests(
            requests.exceptions.ConnectionError,
            urllib3_exc.NameResolutionError(
                "sifen-test.set.gov.py", None, socket.gaierror(11001, "sin DNS")
            ),
        ),
        id="dns",
    ),
    pytest.param(
        lambda: _por_requests(
            requests.exceptions.ConnectionError,
            urllib3_exc.NewConnectionError(
                None, "Failed to establish a new connection: connection refused"
            ),
        ),
        id="conexion_rechazada",
    ),
    pytest.param(
        lambda: _por_requests(
            requests.exceptions.ConnectionError,
            urllib3_exc.NewConnectionError(
                None, "Failed to establish a new connection: network unreachable"
            ),
        ),
        id="red_inalcanzable",
    ),
    pytest.param(
        lambda: _por_requests(
            requests.exceptions.ConnectTimeout,
            urllib3_exc.ConnectTimeoutError(None, "connect timeout=30"),
        ),
        id="timeout_al_conectar",
    ),
    pytest.param(
        lambda: requests.exceptions.ConnectTimeout("sin detalle"),
        id="connect_timeout_sin_cadena",
    ),
    pytest.param(
        lambda: _por_requests(
            requests.exceptions.ProxyError,
            urllib3_exc.ProxyError(
                "Unable to connect to proxy",
                urllib3_exc.NewConnectionError(None, "proxy caido"),
            ),
        ),
        id="proxy_inalcanzable",
    ),
]

FALLOS_AMBIGUOS = [
    pytest.param(
        lambda: requests.exceptions.ReadTimeout(
            urllib3_exc.ReadTimeoutError(None, URL_RECEPCION_PRUEBA, "read timeout=30")
        ),
        id="timeout_de_lectura",
    ),
    pytest.param(
        lambda: requests.exceptions.ConnectionError(
            urllib3_exc.ProtocolError(
                "Connection aborted.", RemoteDisconnected("sin respuesta")
            )
        ),
        id="remote_disconnected",
    ),
    pytest.param(
        lambda: requests.exceptions.ConnectionError(
            urllib3_exc.ProtocolError(
                "Connection aborted.", ConnectionResetError(104, "reset")
            )
        ),
        id="conexion_reiniciada",
    ),
    pytest.param(_ssl_error_tras_el_handshake, id="ssl_tras_handshake"),
    pytest.param(
        lambda: requests.exceptions.ChunkedEncodingError(
            urllib3_exc.ProtocolError("Response ended prematurely")
        ),
        id="respuesta_truncada",
    ),
    pytest.param(
        lambda: requests.exceptions.ConnectionError("sin detalle"),
        id="connection_error_sin_cadena",
    ),
    pytest.param(
        _timeout_mientras_se_maneja_un_fallo_de_conexion,
        id="contexto_ajeno_no_cuenta",
    ),
]


class ServidorLocal:
    """Oyente TCP en 127.0.0.1 (no sale de la maquina) para probar el handshake.

    Sin ``respuesta`` nadie acepta: el kernel completa la conexion TCP y el
    handshake TLS del cliente espera hasta agotar su tiempo. Con
    ``respuesta``, un hilo acepta cada conexion, escribe esos bytes (que no
    son TLS) y la cierra.
    """

    def __init__(self, respuesta: bytes | None = None) -> None:
        self._oyente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._oyente.bind(("127.0.0.1", 0))
        self._oyente.listen(4)
        self.url = f"https://127.0.0.1:{self._oyente.getsockname()[1]}/ws"
        self._hilo: threading.Thread | None = None
        if respuesta is not None:
            self._hilo = threading.Thread(
                target=self._responder, args=(respuesta,), daemon=True
            )
            self._hilo.start()

    def _responder(self, respuesta: bytes) -> None:
        while True:
            try:
                conexion_cliente, _origen = self._oyente.accept()
            except OSError:
                return
            with conexion_cliente:
                conexion_cliente.sendall(respuesta)

    def __enter__(self) -> ServidorLocal:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._oyente.close()
        if self._hilo is not None:
            self._hilo.join(timeout=5)


def _transporte_local(
    pem: tuple[str, str, bytes], max_retries: int, timeout: float = 0.3
) -> Any:
    ruta_certificado, ruta_clave, contrasena = pem
    transporte_http = base._create_transport(
        ruta_certificado,
        ruta_clave,
        timeout=timeout,
        max_retries=max_retries,
        backoff_factor=0.0,
        key_password=contrasena,
    )
    # Que un proxy del entorno no intercepte la conexion local.
    transporte_http._session.trust_env = False
    return transporte_http


class TestSolicitudNoEnviada:
    @pytest.mark.parametrize("fabricar", FALLOS_NO_ENVIADOS)
    def test_fallos_antes_de_enviar(self, fabricar: Callable[[], Exception]) -> None:
        assert conexion.solicitud_no_enviada(fabricar()) is True

    @pytest.mark.parametrize("fabricar", FALLOS_AMBIGUOS)
    def test_fallos_que_pueden_ocurrir_despues_de_enviar(
        self, fabricar: Callable[[], Exception]
    ) -> None:
        assert conexion.solicitud_no_enviada(fabricar()) is False

    def test_error_del_handshake_queda_marcado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        falla = ssl.SSLCertVerificationError(1, "certificate verify failed")

        def handshake_fallido(self: Any, block: bool = False) -> None:
            raise falla

        monkeypatch.setattr(ssl.SSLSocket, "do_handshake", handshake_fallido)
        socket_tls = socket.socket.__new__(conexion._SocketTlsCliente)
        with pytest.raises(ssl.SSLCertVerificationError) as error:
            socket_tls.do_handshake()
        assert error.value is falla
        envuelto = _por_requests(
            requests.exceptions.SSLError, urllib3_exc.SSLError(falla)
        )
        assert conexion.solicitud_no_enviada(envuelto) is True

    def test_contexto_crea_sockets_que_marcan_el_handshake(self) -> None:
        adaptador = conexion.AdaptadorTlsMutuo("c.pem", "k.pem", None)
        try:
            assert adaptador.contexto_tls.sslsocket_class is conexion._SocketTlsCliente
        finally:
            adaptador.close()

    @pytest.mark.parametrize("fabricar", FALLOS_NO_ENVIADOS)
    def test_transporte_lanza_error_tipado_y_reintenta(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        fabricar: Callable[[], Exception],
    ) -> None:
        transporte_http = transporte(max_retries=2)
        fallas = [fabricar() for _ in range(3)]
        sesion = sesion_programada(transporte_http, *fallas)
        with pytest.raises(SifenRequestNotSentError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert len(sesion.llamadas) == 3
        assert error.value.__cause__ is fallas[-1]
        assert not isinstance(error.value, SifenTimeoutError)

    def test_transporte_responde_tras_un_fallo_de_conexion(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        respuesta_http: type[RespuestaHttpFalsa],
    ) -> None:
        transporte_http = transporte(max_retries=1)
        falla = _por_requests(
            requests.exceptions.ConnectionError,
            urllib3_exc.NewConnectionError(None, "connection refused"),
        )
        sesion_programada(transporte_http, falla, respuesta_http(b"<ok/>"))
        assert transporte_http.post(URL_PRUEBA, b"<xml />") == b"<ok/>"

    @pytest.mark.parametrize("fabricar", FALLOS_AMBIGUOS)
    def test_transporte_no_clasifica_ambiguos_como_no_enviados(
        self,
        transporte: Callable[..., Any],
        sesion_programada: Callable[..., SesionProgramada],
        fabricar: Callable[[], Exception],
    ) -> None:
        transporte_http = transporte(max_retries=0)
        sesion_programada(transporte_http, fabricar())
        with pytest.raises(SifenTransportError) as error:
            transporte_http.post(URL_PRUEBA, b"<xml />")
        assert not isinstance(error.value, SifenRequestNotSentError)

    def test_handshake_sin_respuesta_no_llego_al_sifen(
        self, pem_de_prueba: tuple[str, str, bytes]
    ) -> None:
        """Integracion por loopback: el timeout del handshake TLS llega desde
        requests como ``ReadTimeout`` y aun asi se reconoce como no enviado."""
        transporte_http = _transporte_local(pem_de_prueba, max_retries=1)
        try:
            with ServidorLocal() as servidor:
                with pytest.raises(SifenRequestNotSentError) as error:
                    transporte_http.post(servidor.url, b"<xml />")
        finally:
            transporte_http.close()
        assert isinstance(error.value.__cause__, requests.exceptions.ReadTimeout)

    def test_handshake_rechazado_no_llego_al_sifen(
        self, pem_de_prueba: tuple[str, str, bytes]
    ) -> None:
        """Integracion por loopback: el servidor contesta algo que no es TLS y
        cierra. Segun la plataforma, requests lo informa como ``SSLError`` o
        como conexion abortada; en ambos casos el fallo es del handshake."""
        transporte_http = _transporte_local(pem_de_prueba, max_retries=0, timeout=5)
        try:
            with ServidorLocal(b"HTTP/1.1 400 Bad Request\r\n\r\n") as servidor:
                with pytest.raises(SifenRequestNotSentError) as error:
                    transporte_http.post(servidor.url, b"<xml />")
        finally:
            transporte_http.close()
        assert isinstance(error.value.__cause__, requests.exceptions.ConnectionError)


# ---------------------------------------------------------------------------
# Sobres SOAP y extraccion de respuestas (funciones auxiliares de ``base``)
# ---------------------------------------------------------------------------

_PRE = APERTURA_SOBRE
_POST = CIERRE_SOBRE

CASOS_SOBRE_DORADOS = [
    pytest.param(
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<ns0:rEnviConsRUC xmlns:ns0="http://ekuatia.set.gov.py/sifen/xsd">'
        b"<ns0:dId>31</ns0:dId><ns0:dRUCCons>4567012</ns0:dRUCCons>"
        b"</ns0:rEnviConsRUC>",
        _PRE + b'<ns0:rEnviConsRUC xmlns:ns0="http://ekuatia.set.gov.py/sifen/xsd">'
        b"<ns0:dId>31</ns0:dId><ns0:dRUCCons>4567012</ns0:dRUCCons>"
        b"</ns0:rEnviConsRUC>" + _POST,
        id="declaracion_inicial",
    ),
    pytest.param(
        '<?xml-stylesheet href="a"?><r/>',
        _PRE + b"<r/>" + _POST,
        id="xml_stylesheet",
    ),
    pytest.param(
        '  \n<?xml version="1.0"?>\n\n<r/>\n<?xml version="1.0"?>  ',
        _PRE + b'<r/>\n<?xml version="1.0"?>' + _POST,
        id="solo_la_declaracion_inicial",
    ),
    pytest.param(
        "<SOAP:Envelope/>",
        _PRE + b"<SOAP:Envelope/>" + _POST,
        id="otra_grafia_se_envuelve",
    ),
    pytest.param(
        "  <soapenv:Envelope>x</soapenv:Envelope>\n",
        b"<soapenv:Envelope>x</soapenv:Envelope>",
        id="soapenv_sin_envolver",
    ),
    pytest.param(
        '\ufeff<?xml version="1.0"?><r/>',
        _PRE + b'\xef\xbb\xbf<?xml version="1.0"?><r/>' + _POST,
        id="bom",
    ),
]

_SIN_CAMBIOS_TEXTO = (
    f'<soap:Envelope xmlns:soap="{NS_SOAP11}"><soap:Body>texto</soap:Body>'
    "</soap:Envelope>"
).encode()
_SIN_CAMBIOS_VACIO = (
    f'<env:Envelope xmlns:env="{NS_SOAP12}"><env:Body/></env:Envelope>'
).encode()
_SIN_CAMBIOS_SIN_SOBRE = b'<rX xmlns="urn:a"><b/></rX>'

CASOS_BODY_DORADOS = [
    pytest.param(
        f'<soap:Envelope xmlns:soap="{NS_SOAP11}"><soap:Body>'
        "<rRespuesta>ok</rRespuesta></soap:Body></soap:Envelope>".encode(),
        b"<rRespuesta>ok</rRespuesta>",
        id="soap11",
    ),
    pytest.param(
        f'<env:Envelope xmlns:env="{NS_SOAP12}"><env:Body>'
        "<rRetEnviDe>rechazado</rRetEnviDe></env:Body></env:Envelope>".encode(),
        b"<rRetEnviDe>rechazado</rRetEnviDe>",
        id="soap12",
    ),
    pytest.param(
        f'<x:Envelope xmlns:x="{NS_SOAP12}"><x:Body>'
        f'<rResEnviConsRUC xmlns="{NS_SIFEN}"><dCodRes>0502</dCodRes>'
        "</rResEnviConsRUC></x:Body></x:Envelope>".encode(),
        f'<ns0:rResEnviConsRUC xmlns:ns0="{NS_SIFEN}"><ns0:dCodRes>0502'
        "</ns0:dCodRes></ns0:rResEnviConsRUC>".encode(),
        id="hijo_con_namespace",
    ),
    pytest.param(_SIN_CAMBIOS_TEXTO, _SIN_CAMBIOS_TEXTO, id="body_solo_texto"),
    pytest.param(_SIN_CAMBIOS_VACIO, _SIN_CAMBIOS_VACIO, id="body_vacio"),
    pytest.param(_SIN_CAMBIOS_SIN_SOBRE, _SIN_CAMBIOS_SIN_SOBRE, id="sin_sobre"),
    pytest.param(b"garbage", b"garbage", id="no_xml"),
    pytest.param(
        f'<e:Envelope xmlns:e="{NS_SOAP12}"><e:Body>'
        f'<ns2:rRetEnviDe xmlns:ns2="{NS_SIFEN}">'
        f"<ns2:dFecProc>{FECHA_PROCESO}</ns2:dFecProc>"
        f'<Signature xmlns="{NS_XMLDSIG}"><SignedInfo/></Signature>'
        "</ns2:rRetEnviDe>\n  </e:Body></e:Envelope>".encode(),
        f'<ns0:rRetEnviDe xmlns:ns0="{NS_SIFEN}" xmlns:ns1="{NS_XMLDSIG}">'
        f"<ns0:dFecProc>{FECHA_PROCESO}</ns0:dFecProc>"
        "<ns1:Signature><ns1:SignedInfo /></ns1:Signature>"
        "</ns0:rRetEnviDe>\n  ".encode(),
        id="firma_y_cola",
    ),
    pytest.param(
        f'<e:Envelope xmlns:e="{NS_SOAP12}" xmlns:s="{NS_SOAP11}">'
        "<e:Body><a>1</a></e:Body><s:Body><b>2</b></s:Body></e:Envelope>".encode(),
        b"<b>2</b>",
        id="gana_soap11",
    ),
    pytest.param(
        f'<e:Envelope xmlns:e="{NS_SOAP12}"><e:Header><h/></e:Header>'
        "<e:Body><a/><b/></e:Body></e:Envelope>".encode(),
        b"<a />",
        id="solo_primer_hijo",
    ),
    pytest.param(
        b'<?xml version="1.0" encoding="ISO-8859-1"?>'
        b'<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope">'
        b'<e:Body><a x="\xe1">\xe9</a></e:Body></e:Envelope>',
        b'<a x="\xc3\xa1">\xc3\xa9</a>',
        id="iso_8859_1",
    ),
]

CASOS_CUERPO_ERROR_HTTP = [
    pytest.param(requests.exceptions.HTTPError("500"), None, id="sin_response"),
    pytest.param(SimpleNamespace(), None, id="sin_atributo_response"),
    pytest.param(
        requests.exceptions.HTTPError(response=SimpleNamespace(status_code=500)),
        None,
        id="response_sin_content",
    ),
    pytest.param(
        requests.exceptions.HTTPError(response=RespuestaHttpFalsa(b"", 500)),
        None,
        id="content_vacio",
    ),
    pytest.param(
        requests.exceptions.HTTPError(
            response=RespuestaHttpFalsa(
                _sobre_soap12("<rRetEnviDe>rechazado</rRetEnviDe>"), 400
            )
        ),
        b"<rRetEnviDe>rechazado</rRetEnviDe>",
        id="sobre_soap",
    ),
    pytest.param(
        requests.exceptions.HTTPError(
            response=RespuestaHttpFalsa(b"<error>x</error>", 500)
        ),
        b"<error>x</error>",
        id="xml_sin_sobre",
    ),
    pytest.param(
        requests.exceptions.HTTPError(
            response=RespuestaHttpFalsa(b"<html><body>caido", 502)
        ),
        None,
        id="no_xml",
    ),
]

CASOS_IDENTIDAD = [
    pytest.param(
        b'<a:rRetEnviDe xmlns:a="x"><g><dCodRes>0160</dCodRes>'
        b"<dMsgRes>XML Mal</dMsgRes></g></a:rRetEnviDe>",
        ("rRetEnviDe", "0160", "XML Mal"),
        id="codigo_anidado",
    ),
    pytest.param(
        b"<r><dCodRes/><dCodResLot>1</dCodResLot><dMsgResLot>m</dMsgResLot>"
        b"<dCodRes>2</dCodRes></r>",
        ("r", "1", "m"),
        id="lote_y_vacio_no_cuenta",
    ),
    pytest.param(b"no es xml", ("invalid_xml", None, None), id="invalido"),
    pytest.param(
        (
            f'<z:rSinCodigos xmlns:z="{NS_SIFEN}"><z:dato>1</z:dato></z:rSinCodigos>'
        ).encode(),
        ("rSinCodigos", None, None),
        id="sin_codigos",
    ),
]


class TestSobreSoap:
    @pytest.mark.parametrize("entrada, esperado", CASOS_SOBRE_DORADOS)
    def test_wrap_soap_envelope_ejemplos_dorados(
        self, entrada: str | bytes, esperado: bytes
    ) -> None:
        assert base._wrap_soap_envelope(entrada) == esperado

    @pytest.mark.parametrize("entrada, esperado", CASOS_BODY_DORADOS)
    def test_extract_soap_body_ejemplos_dorados(
        self, entrada: bytes, esperado: bytes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # El cuerpo se reserializa con ElementTree, cuyo registro de prefijos es
        # global del proceso: otros modulos de la plataforma registran el
        # espacio SIFEN como espacio por defecto al importarse. Los bytes
        # dorados corresponden a un registro sin esas entradas.
        for espacio in (NS_SIFEN, NS_XMLDSIG):
            monkeypatch.delitem(ET._namespace_map, espacio, raising=False)
        assert base._extract_soap_body(entrada) == esperado

    @pytest.mark.parametrize("excepcion, esperado", CASOS_CUERPO_ERROR_HTTP)
    def test_extract_http_error_xml_body_casos(
        self, excepcion: Any, esperado: bytes | None
    ) -> None:
        assert base._extract_http_error_xml_body(excepcion) == esperado

    @pytest.mark.parametrize("entrada, esperado", CASOS_IDENTIDAD)
    def test_response_identity_casos(
        self, entrada: bytes, esperado: tuple[str, str | None, str | None]
    ) -> None:
        assert base._response_identity(entrada) == esperado


# ---------------------------------------------------------------------------
# Consulta segura
# ---------------------------------------------------------------------------


def _solicitud_ruc() -> REnviConsRuc:
    return REnviConsRuc(dId=4815162342, dRUCCons=RUC_NORMALIZADO)


def _programar_envios(instancia: Any, *respuestas: Any) -> Registrador:
    envios = Registrador(efecto=Secuencia(*respuestas))
    instancia._send_raw_xml = envios
    return envios


def _programar_limpieza(instancia: Any) -> Registrador:
    limpiezas = Registrador()
    instancia._cleanup_transport = limpiezas
    return limpiezas


class TestConsultaSegura:
    def test_consulta_segura_reconecta_tras_protocolo_desajustado(
        self, consulta: Any
    ) -> None:
        """L33."""
        consulta.max_retries = 1
        consulta.retry_backoff = 0
        envios = _programar_envios(consulta, RESPUESTA_AJENA_0160, RESPUESTA_RUC_0502)
        limpiezas = _programar_limpieza(consulta)

        resultado = consulta._send_safe_query(
            "cons_ruc", _solicitud_ruc(), RResEnviConsRuc
        )

        assert resultado.dCodRes == "0502"
        assert envios.veces == 2
        assert limpiezas.llamadas == [((), {})]

    def test_consulta_segura_agota_reintentos_y_lanza_error_tipado(
        self, consulta: Any, esperas: list[float]
    ) -> None:
        """N31."""
        consulta.max_retries = 2
        consulta.retry_backoff = 0.5
        envios = _programar_envios(consulta, RESPUESTA_AJENA_0160)
        limpiezas = _programar_limpieza(consulta)

        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)

        assert envios.veces == 3
        assert limpiezas.veces == 2
        assert esperas == [0.5, 1.0]
        assert isinstance(error.value, SifenTransportError)
        assert error.value.expected_root == "rResEnviConsRUC"
        assert error.value.actual_root == "rRetEnviDe"
        assert error.value.code == "0160"
        assert error.value.response_message == "XML Mal Formado."

    def test_consulta_segura_sin_reintentos_hace_un_solo_intento(
        self, consulta: Any, esperas: list[float]
    ) -> None:
        """N32."""
        envios = _programar_envios(consulta, RESPUESTA_AJENA_0160)
        limpiezas = _programar_limpieza(consulta)
        with pytest.raises(SifenUnexpectedResponseError):
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert envios.veces == 1
        assert limpiezas.veces == 0
        assert esperas == []

    def test_consulta_segura_respuesta_no_xml(self, consulta: Any) -> None:
        """N33."""
        _programar_envios(consulta, b"<<respuesta corrupta")
        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert error.value.actual_root == "invalid_xml"
        assert error.value.code is None
        assert error.value.response_message is None

    def test_consulta_segura_extrae_codigo_y_mensaje_de_lote(
        self, consulta: Any
    ) -> None:
        """N34."""
        respuesta = (
            f'<l:rResEnviConsLoteDe xmlns:l="{NS_SIFEN}">'
            f"<l:dFecProc>{FECHA_PROCESO}</l:dFecProc>"
            "<l:gResultado><l:dCodResLot>0361</l:dCodResLot>"
            "<l:dMsgResLot>Lote en procesamiento</l:dMsgResLot></l:gResultado>"
            "<l:gResProcLote><l:gResProc><l:dCodRes>0260</l:dCodRes>"
            "<l:dMsgRes>Autorizado</l:dMsgRes></l:gResProc></l:gResProcLote>"
            "</l:rResEnviConsLoteDe>"
        ).encode("utf-8")
        _programar_envios(consulta, respuesta)
        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert error.value.actual_root == "rResEnviConsLoteDe"
        assert error.value.code == "0361"
        assert error.value.response_message == "Lote en procesamiento"

    def test_consulta_segura_reenvia_el_mismo_payload(
        self, consulta: Any, esperas: list[float]
    ) -> None:
        """N35; el request se serializa una sola vez."""
        consulta.max_retries = 2
        consulta.retry_backoff = 0.5
        envios = _programar_envios(consulta, RESPUESTA_AJENA_0160)
        _programar_limpieza(consulta)
        serializaciones = Registrador(efecto=consulta._serialize)
        consulta._serialize = serializaciones
        with pytest.raises(SifenUnexpectedResponseError):
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)

        assert serializaciones.veces == 1
        assert envios.veces == 3
        assert {args[0] for args in envios.argumentos} == {"cons_ruc"}
        primero = envios.argumentos[0][1]
        assert RUC_NORMALIZADO in primero
        assert all(args[1] == primero for args in envios.argumentos)

    def test_consulta_segura_exito_inmediato_no_reconecta(
        self, consulta: Any, esperas: list[float]
    ) -> None:
        """N36."""
        consulta.max_retries = 3
        envios = _programar_envios(consulta, RESPUESTA_RUC_0502)
        limpiezas = _programar_limpieza(consulta)
        resultado = consulta._send_safe_query(
            "cons_ruc", _solicitud_ruc(), RResEnviConsRuc
        )
        assert isinstance(resultado, RResEnviConsRuc)
        assert resultado.dMsgRes == "RUC encontrado"
        assert envios.veces == 1
        assert limpiezas.veces == 0
        assert esperas == []

    def test_consulta_segura_error_no_expone_cuerpo(self, consulta: Any) -> None:
        """N69."""
        marca = "Comercial Ficticia del Ycua Bolanos"
        respuesta = (
            f'<rRetEnviDe xmlns="{NS_SIFEN}"><rProtDe>'
            f"<dFecProc>{FECHA_PROCESO}</dFecProc><dNomEmi>{marca}</dNomEmi>"
            "<gResProc><dCodRes>0160</dCodRes><dMsgRes>XML Mal Formado.</dMsgRes>"
            "</gResProc><gResProc><dCodRes>1001</dCodRes>"
            "<dMsgRes>Otro mensaje</dMsgRes></gResProc>"
            "</rProtDe></rRetEnviDe>"
        ).encode("utf-8")
        _programar_envios(consulta, respuesta)
        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert marca not in str(error.value)
        assert all(marca not in str(argumento) for argumento in error.value.args)
        assert error.value.code == "0160"
        assert error.value.response_message == "XML Mal Formado."

    def test_consulta_segura_propaga_errores_de_transporte(self, consulta: Any) -> None:
        consulta.max_retries = 2
        envios = _programar_envios(consulta, SifenTimeoutError("tiempo agotado"))
        with pytest.raises(SifenTimeoutError):
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert envios.veces == 1

    def test_consulta_segura_lee_atributos_en_cada_llamada(
        self, consulta: Any, esperas: list[float]
    ) -> None:
        envios = _programar_envios(consulta, RESPUESTA_AJENA_0160)
        _programar_limpieza(consulta)
        with pytest.raises(SifenUnexpectedResponseError):
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert (envios.veces, esperas) == (1, [])

        consulta.max_retries = 1
        consulta.retry_backoff = 0.25
        with pytest.raises(SifenUnexpectedResponseError):
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert (envios.veces, esperas) == (3, [0.25])

    def test_consulta_segura_con_reintentos_negativos_no_envia(
        self, consulta: Any
    ) -> None:
        consulta.max_retries = -1
        envios = _programar_envios(consulta, RESPUESTA_RUC_0502)
        with pytest.raises(ValueError):
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert envios.veces == 0

    def test_consulta_segura_limpia_antes_de_esperar(
        self, consulta: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        orden: list[Any] = []
        consulta.max_retries = 1
        consulta.retry_backoff = 0.3
        _programar_envios(consulta, RESPUESTA_AJENA_0160, RESPUESTA_RUC_0502)
        consulta._cleanup_transport = lambda: orden.append("limpieza")
        monkeypatch.setattr(time, "sleep", lambda demora: orden.append(demora))

        consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)

        assert orden == ["limpieza", 0.3]

    def test_consulta_segura_error_de_parseo_no_reintenta(self, consulta: Any) -> None:
        """La raiz coincide pero el contenido no es del binding: no se reintenta
        y se informa como respuesta inesperada, no como error de xsdata."""
        consulta.max_retries = 2
        respuesta = (
            f"<rResEnviConsRUC xmlns='{NS_SIFEN}'><dCodRes>0502</dCodRes>"
            "<dMsgRes>RUC encontrado</dMsgRes><dDesconocido>1</dDesconocido>"
            "</rResEnviConsRUC>"
        ).encode("utf-8")
        envios = _programar_envios(consulta, respuesta)
        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert envios.veces == 1
        assert error.value.expected_root == error.value.actual_root == "rResEnviConsRUC"
        assert error.value.code == "0502"
        assert error.value.raw_body == respuesta.decode("utf-8")
        assert isinstance(error.value.__cause__, ParserError)

    def test_consulta_segura_error_incluye_el_cuerpo_recibido(
        self, consulta: Any
    ) -> None:
        _programar_envios(consulta, RESPUESTA_AJENA_0160)
        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta._send_safe_query("cons_ruc", _solicitud_ruc(), RResEnviConsRuc)
        assert error.value.raw_body == RESPUESTA_AJENA_0160.decode("utf-8")


# ---------------------------------------------------------------------------
# Consultas (ConsultaSIFEN)
# ---------------------------------------------------------------------------

RUC_CONTRIBUYENTE = "65432107"
RAZON_SOCIAL = "Yerbatera Ficticia del Guaira SRL"
PROTOCOLO_LOTE = Decimal("3088812007")


SENTINELA_DTE = SimpleNamespace(descripcion="consulta DTE ficticia")


def _respuesta_ruc() -> RResEnviConsRuc:
    return RResEnviConsRuc(dCodRes="0502", dMsgRes="RUC encontrado")


def _sobre_de_otra_operacion() -> SifenUnexpectedResponseError:
    """Lo que lanza el cliente SOAP cuando llega el sobre de otra operacion."""
    return SifenUnexpectedResponseError(
        expected_root="rResEnviConsRUC",
        actual_root="rRetEnviDe",
        code="0160",
        response_message="XML Mal Formado.",
        raw_body=RESPUESTA_AJENA_0160,
    )


RESPUESTAS_POR_SERVICIO = {
    "cons_de": REnviConsDeResponse(
        dFecProc=FECHA_PROCESO, dCodRes="0422", dMsgRes="CDC encontrado"
    ),
    "cons_lote": RResEnviConsLoteDe(
        dFecProc=FECHA_PROCESO, dCodResLot="0361", dMsgResLot="En proceso"
    ),
    "cons_ruc": RResEnviConsRuc(dCodRes="0502", dMsgRes="RUC encontrado"),
    "cons_dte": RConsDteResponse(dFecProc=FECHA_PROCESO, dMsgRes="Procesada"),
    "cons_dte_async": REnviConsDteAsyncResponse(
        dFecProc=FECHA_PROCESO, dProtConsDTEAsync="7770002", dMsgRes="Registrada"
    ),
}

CASOS_REQUEST_POR_CONSULTA = [
    pytest.param(
        lambda c: c.consultar_de(_cdc_ficticio(37)),
        "cons_de",
        lambda r: isinstance(r, REnviConsDeRequest) and r.dCDC == _cdc_ficticio(37),
        True,
        id="consultar_de",
    ),
    pytest.param(
        lambda c: c.consultar_lote(2026031400017),
        "cons_lote",
        lambda r: (
            isinstance(r, REnviConsLoteDe)
            and r.dProtConsLote == Decimal("2026031400017")
        ),
        True,
        id="consultar_lote",
    ),
    pytest.param(
        lambda c: c.consultar_ruc(" 4567012-8 "),
        "cons_ruc",
        lambda r: isinstance(r, REnviConsRuc) and r.dRUCCons == "4567012",
        True,
        id="consultar_ruc",
    ),
    pytest.param(
        lambda c: c.consultar_dte(SENTINELA_DTE),
        "cons_dte",
        lambda r: isinstance(r, RConsDteRequest) and r.rConsultaDTE is SENTINELA_DTE,
        False,
        id="consultar_dte",
    ),
    pytest.param(
        lambda c: c.consultar_dte_async(SENTINELA_DTE),
        "cons_dte_async",
        lambda r: (
            isinstance(r, REnviConsDteAsyncRequest) and r.rConsultaDTE is SENTINELA_DTE
        ),
        False,
        id="consultar_dte_async",
    ),
]


class TestConsultaSIFEN:
    def test_consultar_de_rechaza_cdc_corto(self, consulta: Any) -> None:
        """L23."""
        with pytest.raises(ValueError, match="44 digitos"):
            consulta.consultar_de("123")

    def test_consultar_de_rechaza_cdc_no_numerico(self, consulta: Any) -> None:
        """L24."""
        with pytest.raises(ValueError, match="44 digitos"):
            consulta.consultar_de("Q" * 44)

    def test_consultar_ruc_rechaza_ruc_corto(self, consulta: Any) -> None:
        """L25."""
        with pytest.raises(ValueError, match="de 5 a 8 caracteres"):
            consulta.consultar_ruc("123")

    def test_consultar_ruc_rechaza_ruc_largo(self, consulta: Any) -> None:
        """L26."""
        with pytest.raises(ValueError, match="de 5 a 8 caracteres"):
            consulta.consultar_ruc("987654321")

    def test_consultar_ruc_rechaza_guion_sin_dv(self, consulta: Any) -> None:
        """L27."""
        with pytest.raises(ValueError, match="formato no valido"):
            consulta.consultar_ruc("80024135-")

    def test_consultar_de_devuelve_respuesta_del_cliente(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L28."""
        cliente_soap_falso.respuesta = REnviConsDeResponse(
            dFecProc=FECHA_PROCESO,
            dCodRes="0422",
            dMsgRes="CDC encontrado",
            xContenDE="<contenedor ficticio/>",
        )
        resultado = consulta.consultar_de(_cdc_ficticio(28))
        assert isinstance(resultado, REnviConsDeResponse)
        assert resultado.dCodRes == "0422"

    def test_consultar_lote_devuelve_respuesta_del_cliente(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L29."""
        cliente_soap_falso.respuesta = RResEnviConsLoteDe(
            dFecProc=FECHA_PROCESO,
            dCodResLot="0362",
            dMsgResLot="Procesamiento de lote concluido",
        )
        resultado = consulta.consultar_lote(int(PROTOCOLO_LOTE))
        assert isinstance(resultado, RResEnviConsLoteDe)
        assert resultado.dCodResLot == "0362"

    def test_consultar_ruc_devuelve_datos_del_contribuyente(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L30."""
        cliente_soap_falso.respuesta = RResEnviConsRuc(
            dCodRes="0502",
            dMsgRes="RUC encontrado",
            xContRUC=TContenedorRuc(
                dRUCCons=RUC_CONTRIBUYENTE,
                dRazCons=RAZON_SOCIAL,
                dCodEstCons="ACT",
                dDesEstCons="ACTIVO",
                dRUCFactElec="S",
            ),
        )
        resultado = consulta.consultar_ruc(RUC_CONTRIBUYENTE)
        assert isinstance(resultado, RResEnviConsRuc)
        assert resultado.xContRUC.dRazCons == RAZON_SOCIAL
        assert resultado.xContRUC.dRUCFactElec == "S"

    def test_consultar_ruc_descarta_digito_verificador(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L31."""
        cliente_soap_falso.respuesta = _respuesta_ruc()
        resultado = consulta.consultar_ruc("80024135-5")
        assert resultado.dCodRes == "0502"
        assert cliente_soap_falso.envios[0].dRUCCons == RUC_NORMALIZADO

    def test_consultar_ruc_se_recupera_de_sobre_inesperado(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L32."""
        cliente_soap_falso.error = _sobre_de_otra_operacion()
        limpiezas = _programar_limpieza(consulta)
        recuperada = _respuesta_ruc()
        consulta_segura = Registrador(recuperada)
        consulta._send_safe_query = consulta_segura

        resultado = consulta.consultar_ruc("80024135-5")

        assert resultado is recuperada
        assert limpiezas.llamadas == [((), {})]
        assert consulta_segura.veces == 1

    def test_consultar_dte_devuelve_respuesta_del_cliente(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L34."""
        cliente_soap_falso.respuesta = RConsDteResponse(
            dFecProc=FECHA_PROCESO,
            dMsgRes="Consulta de DTE procesada",
            rConsDte=b"PK\x03\x04archivo-ficticio",
        )
        resultado = consulta.consultar_dte(SENTINELA_DTE)
        assert isinstance(resultado, RConsDteResponse)
        assert resultado.dMsgRes == "Consulta de DTE procesada"

    def test_consultar_dte_async_devuelve_protocolo(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L35."""
        cliente_soap_falso.respuesta = REnviConsDteAsyncResponse(
            dFecProc=FECHA_PROCESO,
            dProtConsDTEAsync="5550001234",
            dMsgRes="Consulta registrada",
        )
        resultado = consulta.consultar_dte_async(SENTINELA_DTE)
        assert isinstance(resultado, REnviConsDteAsyncResponse)
        assert resultado.dProtConsDTEAsync == "5550001234"
        assert resultado.dMsgRes == "Consulta registrada"

    @pytest.mark.parametrize(
        "invocar, servicio, request_valido, con_did", CASOS_REQUEST_POR_CONSULTA
    )
    def test_consultas_construyen_request_y_usan_servicio_correcto(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        invocar: Callable[[Any], Any],
        servicio: str,
        request_valido: Callable[[Any], bool],
        con_did: bool,
    ) -> None:
        """N37."""
        respuesta = RESPUESTAS_POR_SERVICIO[servicio]
        cliente_soap_falso.respuesta = respuesta
        assert invocar(consulta) is respuesta
        assert cliente_soap_falso.servicios == [servicio]
        (enviado,) = cliente_soap_falso.envios
        assert request_valido(enviado)
        if con_did:
            assert isinstance(enviado.dId, int)
            assert 0 < enviado.dId < 10**15

    @pytest.mark.parametrize(
        "protocolo",
        [2026031400017, Decimal("2026031400017"), "2026031400017"],
        ids=["int", "Decimal", "str"],
    )
    def test_consultar_lote_convierte_protocolo_a_decimal(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        protocolo: Any,
    ) -> None:
        """N38."""
        cliente_soap_falso.respuesta = RResEnviConsLoteDe(
            dFecProc=FECHA_PROCESO, dCodResLot="0361", dMsgResLot="En proceso"
        )
        consulta.consultar_lote(protocolo)
        assert cliente_soap_falso.envios[0].dProtConsLote == Decimal("2026031400017")

    def test_consultar_lote_texto_no_numerico_falla_antes_del_cliente(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """N38 (caso no numerico)."""
        with pytest.raises(decimal.InvalidOperation):
            consulta.consultar_lote("protocolo-ficticio")
        assert cliente_soap_falso.servicios == []

    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            (" 80024135 ", RUC_NORMALIZADO),
            ("800 241 35", RUC_NORMALIZADO),
            ("80024135-5", RUC_NORMALIZADO),
            ("12345", "12345"),
            (80024135, RUC_NORMALIZADO),
            ("80024135-55", RUC_NORMALIZADO),
            ("ABCDE", "ABCDE"),
        ],
    )
    def test_consultar_ruc_normalizacion_y_limites(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        entrada: Any,
        esperado: str,
    ) -> None:
        """N39 (entradas validas)."""
        cliente_soap_falso.respuesta = _respuesta_ruc()
        consulta.consultar_ruc(entrada)
        assert cliente_soap_falso.envios[0].dRUCCons == esperado

    @pytest.mark.parametrize(
        "entrada, fragmento",
        [
            ("1234-5", "de 5 a 8 caracteres"),
            ("123456789-0", "de 5 a 8 caracteres"),
            ("1-2-3", "formato no valido"),
            ("-5", "formato no valido"),
            ("80024135-", "formato no valido"),
        ],
    )
    def test_consultar_ruc_normalizacion_rechazos(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        entrada: str,
        fragmento: str,
    ) -> None:
        """N39 (entradas invalidas): no se pide cliente."""
        with pytest.raises(ValueError, match=fragmento):
            consulta.consultar_ruc(entrada)
        assert cliente_soap_falso.servicios == []

    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            (" 4567012 - 8 ", "4567012"),
            ("4567012-8", "4567012"),
            ("45 67 01 2", "4567012"),
            ("\t456701\t", "456701"),
            (4567012, "4567012"),
            ("ABCDE", "ABCDE"),
            ("456\t701", "456\t701"),
        ],
    )
    def test_normalize_ruc_ejemplos(self, entrada: Any, esperado: str) -> None:
        assert _normalize_ruc(entrada) == esperado

    @pytest.mark.parametrize("entrada", ["4567-01-2", "-8", "4567012-"])
    def test_normalize_ruc_formato_invalido(self, entrada: str) -> None:
        with pytest.raises(ValueError, match="formato no valido"):
            _normalize_ruc(entrada)

    @pytest.mark.parametrize(
        "cdc",
        [
            pytest.param("1" * 43, id="43_digitos"),
            pytest.param("1" * 45, id="45_digitos"),
            pytest.param("1" * 43 + " ", id="43_digitos_y_espacio"),
            pytest.param("\u0661" * 44, id="digitos_no_ascii"),
            pytest.param("\uff11" * 44, id="digitos_ancho_completo"),
        ],
    )
    def test_consultar_de_valida_longitud_exacta(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso, cdc: str
    ) -> None:
        """N40; los digitos deben ser ASCII."""
        with pytest.raises(ValueError, match="44 digitos"):
            consulta.consultar_de(cdc)
        assert cliente_soap_falso.servicios == []

    @pytest.mark.parametrize(
        "entrada, tipo_error",
        [(12345, TypeError), (list(range(44)), AttributeError)],
        ids=["entero", "lista"],
    )
    def test_consultar_de_tipos_no_texto(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        entrada: Any,
        tipo_error: type[Exception],
    ) -> None:
        with pytest.raises(tipo_error):
            consulta.consultar_de(entrada)
        assert cliente_soap_falso.servicios == []

    @pytest.mark.parametrize(
        "clase, invocar",
        [
            pytest.param(ConsultaSIFEN, lambda c: c.consultar_de("123"), id="cdc"),
            pytest.param(
                ConsultaSIFEN, lambda c: c.consultar_ruc("123"), id="ruc_corto"
            ),
            pytest.param(
                ConsultaSIFEN, lambda c: c.consultar_ruc("123456789"), id="ruc_largo"
            ),
            pytest.param(
                ConsultaSIFEN, lambda c: c.consultar_ruc("1-2-3"), id="ruc_formato"
            ),
            pytest.param(TransmisionDE, lambda t: t.enviar_lote([]), id="lote_vacio"),
            pytest.param(
                TransmisionDE, lambda t: t.enviar_lote([object()] * 51), id="lote_51"
            ),
        ],
    )
    def test_errores_de_validacion_son_value_error(
        self,
        credenciales_ficticias: dict[str, Any],
        clase: type,
        invocar: Callable[[Any], Any],
    ) -> None:
        """Llegan a la API como 422: deben ser ``ValueError`` y no ``SifenError``."""
        with clase(**credenciales_ficticias) as instancia:
            with pytest.raises(ValueError) as error:
                invocar(instancia)
        assert not isinstance(error.value, SifenError)

    @pytest.mark.parametrize("como_bytes", [False, True], ids=["str", "bytes"])
    @pytest.mark.parametrize(
        "clase, invocar, respuesta",
        [
            pytest.param(
                ConsultaSIFEN,
                lambda i: i.consultar_de(_cdc_ficticio(41)),
                REnviConsDeResponse(
                    dFecProc=FECHA_PROCESO, dCodRes="0422", dMsgRes="CDC encontrado"
                ),
                id="consultar_de",
            ),
            pytest.param(
                ConsultaSIFEN,
                lambda i: i.consultar_lote(41),
                RResEnviConsLoteDe(
                    dFecProc=FECHA_PROCESO, dCodResLot="0362", dMsgResLot="Concluido"
                ),
                id="consultar_lote",
            ),
            pytest.param(
                ConsultaSIFEN,
                lambda i: i.consultar_ruc(RUC_CONTRIBUYENTE),
                RResEnviConsRuc(
                    dCodRes="0502",
                    dMsgRes="RUC encontrado",
                    xContRUC=TContenedorRuc(
                        dRUCCons=RUC_CONTRIBUYENTE,
                        dRazCons=RAZON_SOCIAL,
                        dCodEstCons="ACT",
                        dDesEstCons="ACTIVO",
                        dRUCFactElec="N",
                    ),
                ),
                id="consultar_ruc",
            ),
            pytest.param(
                ConsultaSIFEN,
                lambda i: i.consultar_dte(SENTINELA_DTE),
                RConsDteResponse(
                    dFecProc=FECHA_PROCESO, dMsgRes="Procesada", rConsDte=b"zip"
                ),
                id="consultar_dte",
            ),
            pytest.param(
                ConsultaSIFEN,
                lambda i: i.consultar_dte_async(SENTINELA_DTE),
                REnviConsDteAsyncResponse(
                    dFecProc=FECHA_PROCESO,
                    dProtConsDTEAsync="7770001",
                    dMsgRes="Registrada",
                ),
                id="consultar_dte_async",
            ),
            pytest.param(
                TransmisionEvento,
                lambda i: i.enviar_evento(SENTINELA_DTE),
                RRetEnviEventoDe(
                    dFecProc=FECHA_PROCESO,
                    gResProcEVe=[
                        TgResProcEve(
                            dEstRes="Aprobado",
                            dProtAut=4401920517,
                            id="41",
                            gResProc=[TgResProc(dCodRes="0600", dMsgRes="Evento ok")],
                        )
                    ],
                ),
                id="enviar_evento",
            ),
            pytest.param(
                TransmisionDE,
                lambda i: i.enviar_lote_xml([_rde_lote(_cdc_ficticio(41))]),
                RResEnviLoteDe(
                    dFecProc=FECHA_PROCESO,
                    dCodRes="0300",
                    dMsgRes="Lote recibido",
                    dProtConsLote=PROTOCOLO_LOTE,
                    dTpoProces=4,
                ),
                id="enviar_lote",
            ),
        ],
    )
    def test_respuestas_en_texto_o_bytes_se_parsean(
        self,
        credenciales_ficticias: dict[str, Any],
        cliente_soap_falso: ClienteSoapFalso,
        monkeypatch: pytest.MonkeyPatch,
        clase: type,
        invocar: Callable[[Any], Any],
        respuesta: Any,
        como_bytes: bool,
    ) -> None:
        """N41."""
        texto = _xml_de_binding(respuesta)
        cliente_soap_falso.respuesta = texto.encode("utf-8") if como_bytes else texto
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador("<rDE/>"))
        monkeypatch.setattr(TransmisionBase, "_sign_xml", Registrador("<rDE/>"))
        with clase(**credenciales_ficticias) as instancia:
            resultado = invocar(instancia)
        assert isinstance(resultado, type(respuesta))
        assert resultado == respuesta

    def test_consultar_ruc_recuperacion_reutiliza_el_mismo_request(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """N42."""
        cliente_soap_falso.error = _sobre_de_otra_operacion()
        _programar_limpieza(consulta)
        consulta_segura = Registrador(_respuesta_ruc())
        consulta._send_safe_query = consulta_segura

        consulta.consultar_ruc("80024135-5")

        ((servicio, solicitud, tipo),) = consulta_segura.argumentos
        assert servicio == "cons_ruc"
        assert solicitud.dRUCCons == RUC_NORMALIZADO
        assert solicitud is cliente_soap_falso.envios[0]
        assert tipo is RResEnviConsRuc
        assert consulta_segura.llamadas[0][1] == {}

    def test_consultar_ruc_recuperacion_no_normaliza_respuesta(
        self, consulta: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        cliente_soap_falso.error = _sobre_de_otra_operacion()
        _programar_limpieza(consulta)
        centinela = object()
        consulta._send_safe_query = Registrador(centinela)
        assert consulta.consultar_ruc(RUC_CONTRIBUYENTE) is centinela

    @pytest.mark.parametrize(
        "falla",
        [
            pytest.param(SifenTransportError("fallo de red"), id="transporte"),
            pytest.param(SifenTimeoutError("tiempo agotado"), id="timeout"),
            pytest.param(TypeError("campo obligatorio ausente"), id="type_error"),
        ],
    )
    def test_consultar_ruc_no_recupera_otros_errores(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        falla: Exception,
    ) -> None:
        """N43."""
        cliente_soap_falso.error = falla
        limpiezas = _programar_limpieza(consulta)
        consulta_segura = Registrador()
        consulta._send_safe_query = consulta_segura
        with pytest.raises(type(falla)) as error:
            consulta.consultar_ruc(RUC_CONTRIBUYENTE)
        assert error.value is falla
        assert limpiezas.veces == 0
        assert consulta_segura.veces == 0

    @pytest.mark.parametrize(
        "invocar",
        [
            pytest.param(lambda c: c.consultar_de(_cdc_ficticio(44)), id="de"),
            pytest.param(lambda c: c.consultar_lote(44), id="lote"),
            pytest.param(lambda c: c.consultar_dte(SENTINELA_DTE), id="dte"),
            pytest.param(
                lambda c: c.consultar_dte_async(SENTINELA_DTE), id="dte_async"
            ),
        ],
    )
    def test_otras_consultas_no_recuperan_respuesta_inesperada(
        self,
        consulta: Any,
        cliente_soap_falso: ClienteSoapFalso,
        invocar: Callable[[Any], Any],
    ) -> None:
        """N44."""
        falla = _sobre_de_otra_operacion()
        cliente_soap_falso.error = falla
        consulta_segura = Registrador()
        consulta._send_safe_query = consulta_segura
        with pytest.raises(SifenUnexpectedResponseError) as error:
            invocar(consulta)
        assert error.value is falla
        assert consulta_segura.veces == 0


# ---------------------------------------------------------------------------
# Integracion sin red: cliente xsdata real + transporte real
# ---------------------------------------------------------------------------


def _did_enviado(datos: bytes) -> str:
    return _hijo_local(ET.fromstring(datos), "dId").text


class TestIntegracionSinRed:
    def test_integracion_consultar_ruc_por_soap12(
        self, consulta: Any, red_simulada: Callable[..., RedSimulada]
    ) -> None:
        """N45."""
        red = red_simulada(RespuestaHttpFalsa(_sobre_soap12(CUERPO_RUC_PREFIJADO)))

        resultado = consulta.consultar_ruc("80024135-5")

        assert isinstance(resultado, RResEnviConsRuc)
        assert resultado.dCodRes == "0502"
        (envio,) = red.llamadas
        assert envio.url == get_endpoint(TEST, "cons_ruc")
        assert envio.data.startswith(APERTURA_SOBRE)
        assert b"rEnviConsRUC" in envio.data
        assert RUC_NORMALIZADO.encode("ascii") in envio.data
        assert envio.headers == {"Content-Type": TIPO_CONTENIDO_SOAP12}
        assert envio.timeout == 30.0

    def test_integracion_consultar_ruc_reconecta_tras_sobre_ajeno(
        self, consulta: Any, red_simulada: Callable[..., RedSimulada]
    ) -> None:
        """N46."""
        red = red_simulada(
            RespuestaHttpFalsa(_sobre_soap12(CUERPO_RET_ENVI_DE_PREFIJADO)),
            RespuestaHttpFalsa(_sobre_soap12(CUERPO_RUC_PREFIJADO)),
        )

        resultado = consulta.consultar_ruc("80024135-5")

        assert isinstance(resultado, RResEnviConsRuc)
        assert resultado.dCodRes == "0502"
        assert len(red.llamadas) == 2
        assert red.llamadas[1].sesion is not red.llamadas[0].sesion

    def test_integracion_consultar_ruc_sobre_ajeno_persistente(
        self, consulta: Any, red_simulada: Callable[..., RedSimulada]
    ) -> None:
        """N47."""
        red = red_simulada(
            RespuestaHttpFalsa(_sobre_soap12(CUERPO_RET_ENVI_DE_PREFIJADO))
        )
        with pytest.raises(SifenUnexpectedResponseError) as error:
            consulta.consultar_ruc("80024135-5")
        assert error.value.expected_root == "rResEnviConsRUC"
        assert error.value.actual_root == "rRetEnviDe"
        assert error.value.code == "0160"
        assert error.value.response_message == "XML Mal Formado."
        assert len(red.llamadas) == 2

    def test_integracion_consultar_ruc_con_reintentos(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
    ) -> None:
        """N48."""
        red = red_simulada(
            RespuestaHttpFalsa(_sobre_soap12(CUERPO_RET_ENVI_DE_PREFIJADO))
        )
        with ConsultaSIFEN(
            **credenciales_ficticias, max_retries=2, retry_backoff=0
        ) as consulta_reintentos:
            with pytest.raises(SifenUnexpectedResponseError):
                consulta_reintentos.consultar_ruc("80024135-5")
        assert len(red.llamadas) == 4
        identificadores = {_did_enviado(llamada.data) for llamada in red.llamadas}
        assert len(identificadores) == 1


# ---------------------------------------------------------------------------
# Politica de reintentos: envios con efecto fiscal frente a consultas
# ---------------------------------------------------------------------------


def _fallo_de_conexion_rechazada() -> Exception:
    return _por_requests(
        requests.exceptions.ConnectionError,
        urllib3_exc.NewConnectionError(None, "connection refused"),
    )


FALLOS_AMBIGUOS_DE_RED = [
    pytest.param(
        lambda: requests.exceptions.ReadTimeout("sin respuesta"),
        SifenTimeoutError,
        id="timeout_de_lectura",
    ),
    pytest.param(
        lambda: requests.exceptions.ConnectionError(
            urllib3_exc.ProtocolError(
                "Connection aborted.", RemoteDisconnected("conexion cerrada")
            )
        ),
        SifenTransportError,
        id="conexion_cortada",
    ),
    pytest.param(
        lambda: RespuestaHttpFalsa(b"", 503), SifenTransportError, id="http_503"
    ),
]


def _enviar_de_xml(credenciales: dict[str, Any]) -> None:
    with TransmisionDE(**credenciales) as transmision:
        transmision.enviar_de_xml(_rde_sifen(_cdc_ficticio(90)))


def _enviar_lote(credenciales: dict[str, Any]) -> None:
    with TransmisionDE(**credenciales) as transmision:
        transmision.enviar_lote_xml([_rde_lote(_cdc_ficticio(91))], lote_id=91)


def _enviar_evento(credenciales: dict[str, Any]) -> None:
    with TransmisionEvento(**credenciales) as transmision:
        transmision.enviar_evento(TgGroupGesEve())


def _enviar_evento_crudo(credenciales: dict[str, Any]) -> None:
    with TransmisionEvento(**credenciales) as transmision:
        transmision._send_raw_xml(
            "evento", f"<rEnviEventoDe xmlns='{NS_SIFEN}'><dId>92</dId></rEnviEventoDe>"
        )


ENVIOS_CON_EFECTO_FISCAL = [
    pytest.param(_enviar_de_xml, id="recepcion_de"),
    pytest.param(_enviar_lote, id="lote"),
    pytest.param(_enviar_evento, id="evento"),
    pytest.param(_enviar_evento_crudo, id="evento_crudo"),
]


class TestPoliticaDeReintentos:
    def test_solo_las_consultas_reintentan_fallos_ambiguos(self) -> None:
        assert TransmisionBase._REINTENTA_ERRORES_AMBIGUOS is False
        assert TransmisionDE._REINTENTA_ERRORES_AMBIGUOS is False
        assert TransmisionEvento._REINTENTA_ERRORES_AMBIGUOS is False
        assert ConsultaSIFEN._REINTENTA_ERRORES_AMBIGUOS is True

    @pytest.mark.parametrize("fabricar, tipo_error", FALLOS_AMBIGUOS_DE_RED)
    @pytest.mark.parametrize("enviar", ENVIOS_CON_EFECTO_FISCAL)
    def test_envio_fiscal_no_reintenta_un_fallo_ambiguo(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
        esperas: list[float],
        enviar: Callable[[dict[str, Any]], None],
        fabricar: Callable[[], Any],
        tipo_error: type[Exception],
    ) -> None:
        """Aun con ``max_retries`` alto, un resultado incierto sale enseguida."""
        red = red_simulada(fabricar())
        with pytest.raises(SifenTransportError) as error:
            enviar({**credenciales_ficticias, "max_retries": 3})
        assert type(error.value) is tipo_error
        assert len(red.llamadas) == 1
        assert esperas == []

    @pytest.mark.parametrize("enviar", ENVIOS_CON_EFECTO_FISCAL)
    def test_envio_fiscal_reintenta_si_la_solicitud_no_salio(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
        esperas: list[float],
        enviar: Callable[[dict[str, Any]], None],
    ) -> None:
        red = red_simulada(_fallo_de_conexion_rechazada())
        with pytest.raises(SifenRequestNotSentError):
            enviar({**credenciales_ficticias, "max_retries": 2, "retry_backoff": 0.5})
        assert len(red.llamadas) == 3
        assert esperas == [0.5, 1.0]

    def test_envio_fiscal_sale_tras_conexion_rechazada_y_luego_timeout(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
    ) -> None:
        """El reintento por conexion rechazada no habilita reintentar despues
        un timeout de lectura."""
        red = red_simulada(
            _fallo_de_conexion_rechazada(),
            requests.exceptions.ReadTimeout("sin respuesta"),
            RespuestaHttpFalsa(_sobre_soap12(CUERPO_RET_ENVI_DE_PREFIJADO)),
        )
        with pytest.raises(SifenTimeoutError):
            _enviar_de_xml({**credenciales_ficticias, "max_retries": 5})
        assert len(red.llamadas) == 2

    @pytest.mark.parametrize("fabricar, tipo_error", FALLOS_AMBIGUOS_DE_RED)
    def test_consulta_reintenta_fallos_ambiguos(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
        fabricar: Callable[[], Any],
        tipo_error: type[Exception],
    ) -> None:
        red = red_simulada(fabricar())
        with ConsultaSIFEN(
            **credenciales_ficticias, max_retries=2, retry_backoff=0
        ) as consulta_reintentos:
            with pytest.raises(SifenTransportError) as error:
                consulta_reintentos.consultar_de(_cdc_ficticio(93))
        assert type(error.value) is tipo_error
        assert len(red.llamadas) == 3


# ---------------------------------------------------------------------------
# Respuestas inesperadas: SOAP Fault, HTML de un proxy, cuerpo ilegible
# ---------------------------------------------------------------------------

MOTIVO_FAULT = "Error interno del servicio ficticio"

FAULT_SOAP12 = (
    f'<env:Envelope xmlns:env="{NS_SOAP12}"><env:Body><env:Fault>'
    "<env:Code><env:Value>env:Receiver</env:Value></env:Code>"
    f'<env:Reason><env:Text xml:lang="es">{MOTIVO_FAULT}</env:Text></env:Reason>'
    "</env:Fault></env:Body></env:Envelope>"
).encode("utf-8")

FAULT_SOAP11 = (
    f'<s:Envelope xmlns:s="{NS_SOAP11}"><s:Body><s:Fault>'
    f"<faultcode>s:Server</faultcode><faultstring>{MOTIVO_FAULT}</faultstring>"
    "</s:Fault></s:Body></s:Envelope>"
).encode("utf-8")

RESPUESTAS_INESPERADAS = [
    pytest.param(
        lambda: RespuestaHttpFalsa(FAULT_SOAP12, 500),
        "Fault",
        MOTIVO_FAULT,
        id="fault_soap12_http500",
    ),
    pytest.param(
        lambda: RespuestaHttpFalsa(FAULT_SOAP12, 200),
        "Fault",
        MOTIVO_FAULT,
        id="fault_soap12_http200",
    ),
    pytest.param(
        lambda: RespuestaHttpFalsa(FAULT_SOAP11, 500),
        "Fault",
        MOTIVO_FAULT,
        id="fault_soap11",
    ),
    pytest.param(
        lambda: RespuestaHttpFalsa(b"<html><body>502 Bad Gateway</body></html>"),
        "html",
        "502 Bad Gateway",
        id="html_de_proxy",
    ),
    pytest.param(
        lambda: RespuestaHttpFalsa(b"respuesta cortada <rRetEnviDe"),
        "invalid_xml",
        "respuesta cortada",
        id="no_xml",
    ),
    pytest.param(lambda: RespuestaHttpFalsa(b""), "invalid_xml", "", id="vacia"),
]


def _enviar_de_sin_firma(transmision: Any) -> Any:
    transmision._serialize = lambda *_args, **_kwargs: _rde_sifen(_cdc_ficticio(95))
    return transmision.enviar_de(SimpleNamespace(DE=None), sign=False)


OPERACIONES_CON_RESPUESTA = [
    pytest.param(
        TransmisionDE,
        lambda t: t.enviar_de_xml(_rde_sifen(_cdc_ficticio(94))),
        "rRetEnviDe",
        1,
        id="enviar_de_xml",
    ),
    pytest.param(TransmisionDE, _enviar_de_sin_firma, "rRetEnviDe", 1, id="enviar_de"),
    pytest.param(
        TransmisionDE,
        lambda t: t.enviar_lote_xml([_rde_lote(_cdc_ficticio(96))], lote_id=96),
        "rResEnviLoteDe",
        1,
        id="enviar_lote",
    ),
    pytest.param(
        TransmisionEvento,
        lambda t: t.enviar_evento(TgGroupGesEve()),
        "rRetEnviEventoDe",
        1,
        id="enviar_evento",
    ),
    pytest.param(
        ConsultaSIFEN,
        lambda t: t.consultar_de(_cdc_ficticio(97)),
        "rEnviConsDeResponse",
        1,
        id="consultar_de",
    ),
    pytest.param(
        ConsultaSIFEN,
        lambda t: t.consultar_lote(97),
        "rResEnviConsLoteDe",
        1,
        id="consultar_lote",
    ),
    pytest.param(
        ConsultaSIFEN,
        lambda t: t.consultar_ruc("80024135-5"),
        "rResEnviConsRUC",
        2,  # el sobre inesperado activa la reconexion de consultar_ruc
        id="consultar_ruc",
    ),
    pytest.param(
        ConsultaSIFEN,
        lambda t: t.consultar_dte(None),
        "rConsDteResponse",
        1,
        id="consultar_dte",
    ),
    pytest.param(
        ConsultaSIFEN,
        lambda t: t.consultar_dte_async(None),
        "rEnviConsDteAsyncResponse",
        1,
        id="consultar_dte_async",
    ),
]


class TestRespuestasInesperadas:
    @pytest.mark.parametrize("fabricar, raiz, fragmento", RESPUESTAS_INESPERADAS)
    @pytest.mark.parametrize(
        "clase, operar, raiz_esperada, envios_esperados", OPERACIONES_CON_RESPUESTA
    )
    def test_toda_operacion_informa_respuesta_inesperada(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
        clase: type,
        operar: Callable[[Any], Any],
        raiz_esperada: str,
        envios_esperados: int,
        fabricar: Callable[[], Any],
        raiz: str,
        fragmento: str,
    ) -> None:
        red = red_simulada(fabricar())
        with clase(**credenciales_ficticias) as transmision:
            with pytest.raises(SifenUnexpectedResponseError) as error:
                operar(transmision)
        assert isinstance(error.value, SifenTransportError)
        assert error.value.expected_root == raiz_esperada
        assert error.value.actual_root == raiz
        assert error.value.raw_body is not None
        assert fragmento in error.value.raw_body
        assert len(red.llamadas) == envios_esperados

    def test_mensaje_en_espanol_sin_el_cuerpo(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
    ) -> None:
        red_simulada(RespuestaHttpFalsa(FAULT_SOAP12, 500))
        with TransmisionDE(**credenciales_ficticias) as transmision:
            with pytest.raises(SifenUnexpectedResponseError) as error:
                transmision.enviar_de_xml(_rde_sifen(_cdc_ficticio(98)))
        assert str(error.value) == (
            "Respuesta inesperada del SIFEN: se esperaba rRetEnviDe y se recibio Fault"
        )
        assert MOTIVO_FAULT not in str(error.value)

    def test_raiz_correcta_sin_campo_obligatorio(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
    ) -> None:
        cuerpo = f'<rRetEnviDe xmlns="{NS_SIFEN}"/>'
        red_simulada(RespuestaHttpFalsa(_sobre_soap12(cuerpo)))
        with TransmisionDE(**credenciales_ficticias) as transmision:
            with pytest.raises(SifenUnexpectedResponseError) as error:
                transmision.enviar_de_xml(_rde_sifen(_cdc_ficticio(99)))
        assert error.value.actual_root == "rRetEnviDe"
        assert isinstance(error.value.__cause__, TypeError)

    def test_cuerpo_largo_se_recorta(self, transmision_de: Any) -> None:
        relleno = "x" * (2 * MAX_CUERPO_CRUDO)
        transmision_de._send_raw_xml = Registrador(f"<html>{relleno}</html>".encode())
        with pytest.raises(SifenUnexpectedResponseError) as error:
            transmision_de.enviar_de_xml(_rde_sifen(_cdc_ficticio(100)))
        assert len(error.value.raw_body) == MAX_CUERPO_CRUDO
        assert error.value.raw_body.startswith("<html>xxx")

    def test_parser_de_respuestas_sin_clase_delega_en_xsdata(self) -> None:
        texto = f'<rResEnviConsRUC xmlns="{NS_SIFEN}"><dCodRes>0502</dCodRes>'
        texto += "<dMsgRes>RUC encontrado</dMsgRes></rResEnviConsRUC>"
        parser = base._parser_de_respuestas()
        resultado = parser.from_bytes(texto.encode(), RResEnviConsRuc)
        assert resultado == _respuesta_ruc()
        with pytest.raises(ParserError):
            parser.from_bytes(b"<desconocido/>")


# ---------------------------------------------------------------------------
# Documentos electronicos (TransmisionDE)
# ---------------------------------------------------------------------------

_DECLARACION_SOLICITUD = b"<?xml version='1.0' encoding='UTF-8'?>\n"
# El rDE conserva su propia declaracion del namespace del SIFEN (aunque
# rEnviDe tambien la tenga) y recibe xsi:schemaLocation.
_DECLARACIONES_ESQUEMA = (
    b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    b'xsi:schemaLocation="http://ekuatia.set.gov.py/sifen/xsd siRecepDE_v150.xsd"'
)
_RDE_CON_ESQUEMA = (
    b'<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd" ' + _DECLARACIONES_ESQUEMA
)


def _solicitud_esperada(d_id: bytes, contenido_xde: bytes) -> bytes:
    return (
        _DECLARACION_SOLICITUD
        + b'<rEnviDe xmlns="http://ekuatia.set.gov.py/sifen/xsd"><dId>'
        + d_id
        + b"</dId><xDE>"
        + contenido_xde
        + b"</xDE></rEnviDe>"
    )


CASOS_SOLICITUD_DORADOS = [
    pytest.param(
        1,
        f'<rDE xmlns="{NS_SIFEN}"><DE Id="A1"><a>1</a></DE></rDE>',
        _solicitud_esperada(
            b"1", _RDE_CON_ESQUEMA + b'><DE Id="A1"><a>1</a></DE></rDE>'
        ),
        id="basico",
    ),
    pytest.param(
        42,
        f'<?xml version="1.0" encoding="UTF-8"?>\n<rDE xmlns="{NS_SIFEN}">'
        '<DE Id="A1"/></rDE>',
        _solicitud_esperada(b"42", _RDE_CON_ESQUEMA + b'><DE Id="A1"/></rDE>'),
        id="con_declaracion",
    ),
    pytest.param(
        2,
        f'<rDE xmlns="{NS_SIFEN}" xmlns:xsi="{NS_XSI}" xsi:schemaLocation="custom">'
        '<DE Id="1"/></rDE>',
        _solicitud_esperada(
            b"2",
            b'<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd" '
            b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            b'xsi:schemaLocation="custom"><DE Id="1"/></rDE>',
        ),
        id="schema_location_propio",
    ),
    pytest.param(
        3,
        f'<ns0:rDE xmlns:ns0="{NS_SIFEN}"><ns0:DE Id="1"/></ns0:rDE>',
        _solicitud_esperada(
            b"3",
            b'<ns0:rDE xmlns:ns0="http://ekuatia.set.gov.py/sifen/xsd" '
            + _DECLARACIONES_ESQUEMA
            + b'><ns0:DE Id="1"/></ns0:rDE>',
        ),
        id="prefijado_se_conserva",
    ),
    pytest.param(
        1,
        f'<rDE xmlns="{NS_SIFEN}"><dVerFor>150</dVerFor><DE Id="0180"><a>1</a></DE>'
        f'<Signature xmlns="{NS_XMLDSIG}"><SignedInfo/></Signature></rDE>',
        _solicitud_esperada(
            b"1",
            _RDE_CON_ESQUEMA + b'><dVerFor>150</dVerFor><DE Id="0180"><a>1</a></DE>'
            b'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignedInfo/>'
            b"</Signature></rDE>",
        ),
        id="con_firma",
    ),
    pytest.param(
        5,
        '<rDE><DE Id="1"/></rDE>',
        _solicitud_esperada(
            b"5", b"<rDE " + _DECLARACIONES_ESQUEMA + b'><DE Id="1"/></rDE>'
        ),
        id="sin_namespace",
    ),
    pytest.param(
        6,
        f'<rDE xmlns="{NS_SIFEN}">\n  <DE Id="1"/>\n</rDE>\n',
        _solicitud_esperada(b"6", _RDE_CON_ESQUEMA + b'>\n  <DE Id="1"/>\n</rDE>'),
        id="blancos_internos",
    ),
    pytest.param(
        7,
        f'<!-- c --><rDE xmlns="{NS_SIFEN}"><DE Id="1"/></rDE>',
        _solicitud_esperada(b"7", _RDE_CON_ESQUEMA + b'><DE Id="1"/></rDE>'),
        id="comentario_exterior",
    ),
    pytest.param(
        8,
        f'<rDE xmlns="{NS_SIFEN}"><DE Id="1">\u00f1</DE></rDE>',
        _solicitud_esperada(
            b"8", _RDE_CON_ESQUEMA + b'><DE Id="1">\xc3\xb1</DE></rDE>'
        ),
        id="no_ascii",
    ),
    pytest.param(
        9,
        f'<?xml version="1.0" encoding="ISO-8859-1"?><rDE xmlns="{NS_SIFEN}">'
        "<a>\u00f1</a></rDE>",
        _solicitud_esperada(b"9", _RDE_CON_ESQUEMA + b"><a>\xc3\x83\xc2\xb1</a></rDE>"),
        id="codificacion_declarada_distinta",
    ),
    pytest.param(
        "x",
        f'<rDE xmlns="{NS_SIFEN}"/>',
        _solicitud_esperada(b"x", _RDE_CON_ESQUEMA + b"/>"),
        id="d_id_no_entero",
    ),
    pytest.param(
        "<&>",
        f'<rDE xmlns="{NS_SIFEN}"/>',
        _solicitud_esperada(b"&lt;&amp;&gt;", _RDE_CON_ESQUEMA + b"/>"),
        id="d_id_se_escapa",
    ),
]


def _solicitud_por_constructor(_transmision_de: Any, firmado: str) -> bytes:
    return _build_enviar_de_request_xml(1, firmado)


def _solicitud_por_enviar_de_xml(transmision_de: Any, firmado: str) -> bytes:
    envios = Registrador(_ret_envi_de_minimo())
    transmision_de._send_raw_xml = envios
    transmision_de.enviar_de_xml(firmado)
    return envios.argumentos[0][1]


def _enviar_de_xml_por_defecto(credenciales: dict[str, Any]) -> None:
    with TransmisionDE(**credenciales) as transmision:
        transmision.enviar_de_xml(_rde_sifen(_cdc_ficticio(59)))


def _enviar_evento_crudo_por_defecto(credenciales: dict[str, Any]) -> None:
    with TransmisionEvento(**credenciales) as transmision:
        transmision._send_raw_xml(
            "evento",
            f"<rEnviEventoDe xmlns='{NS_SIFEN}'><dId>59</dId></rEnviEventoDe>",
        )


class TestTransmisionDE:
    def test_constructor_guarda_ambiente_y_credenciales(
        self, transmision_de: Any, credenciales_ficticias: dict[str, Any]
    ) -> None:
        """L16."""
        assert transmision_de.ambiente == 2
        assert transmision_de.pkcs12_data is credenciales_ficticias["pkcs12_data"]
        assert (
            transmision_de.pkcs12_password is credenciales_ficticias["pkcs12_password"]
        )

    def test_enviar_de_firma_y_envuelve_en_renvide(
        self,
        transmision_de: Any,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """L17."""
        cdc = _cdc_ficticio(17)
        firmador = Registrador(_rde_sifen(cdc, "<dMarca>firmado-en-prueba</dMarca>"))
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador(_rde_sifen(cdc)))
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        aprobada = RRetEnviDe(
            rProtDe=RProtDe(
                Id=cdc,
                dFecProc=FECHA_PROCESO,
                dEstRes="Aprobado",
                dProtAut=4401920517,
                gResProc=[TgResProc(dCodRes="0260", dMsgRes="Autorizado el DE")],
            )
        )
        envios = Registrador(aprobada)
        transmision_de._send_raw_xml = envios

        rde = rde_simulado(cdc)
        resultado = transmision_de.enviar_de(rde)

        assert isinstance(resultado, RRetEnviDe)
        assert resultado is aprobada
        assert resultado.rProtDe.dEstRes == "Aprobado"
        assert resultado.rProtDe.dProtAut == 4401920517
        assert resultado.rProtDe.gResProc[0].dCodRes == "0260"
        assert firmador.veces == 1
        assert firmador.argumentos[0][1] == rde.DE.Id
        servicio, solicitud = envios.argumentos[0]
        assert servicio == "recep_de"
        assert isinstance(solicitud, bytes)
        assert b"<xDE>" in solicitud
        assert b"firmado-en-prueba" in solicitud
        assert b"schemaLocation" in solicitud

    def test_enviar_lote_rechaza_mas_de_cincuenta(self, transmision_de: Any) -> None:
        """L18."""
        with pytest.raises(ValueError, match="como maximo 50"):
            transmision_de.enviar_lote([object()] * (MAX_LOTE + 1))

    def test_enviar_lote_rechaza_lista_vacia(self, transmision_de: Any) -> None:
        """L19."""
        with pytest.raises(ValueError, match="al menos un documento"):
            transmision_de.enviar_lote([])

    def test_enviar_lote_firma_cada_de_y_devuelve_protocolo(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """L20."""
        cliente_soap_falso.respuesta = RResEnviLoteDe(
            dFecProc=FECHA_PROCESO,
            dCodRes="0300",
            dMsgRes="Lote recibido con exito",
            dProtConsLote=PROTOCOLO_LOTE,
            dTpoProces=3,
        )
        firmador = Registrador(
            efecto=lambda _xml, doc_id: _rde_lote(doc_id, extra="<firmado/>")
        )
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador("<rDE/>"))
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        documentos = [rde_simulado(_cdc_ficticio(n)) for n in (201, 202, 203)]

        resultado = transmision_de.enviar_lote(documentos, lote_id=999)

        assert isinstance(resultado, RResEnviLoteDe)
        assert resultado.dCodRes == "0300"
        assert resultado.dProtConsLote == PROTOCOLO_LOTE
        assert firmador.argumentos == [("<rDE/>", rde.DE.Id) for rde in documentos]
        assert cliente_soap_falso.servicios == ["recep_lote"]
        _nombres, contenido = _abrir_zip_lote(cliente_soap_falso.envios[0].xDE)
        assert contenido.count(b"<firmado/>") == 3

    def test_enviar_de_sin_firma_no_invoca_firmador(self, transmision_de: Any) -> None:
        """L21."""
        envios = Registrador(
            RRetEnviDe(
                rProtDe=RProtDe(
                    dFecProc=FECHA_PROCESO,
                    gResProc=[TgResProc(dCodRes="0260", dMsgRes="Autorizado")],
                )
            )
        )
        firmador = Registrador()
        transmision_de._send_raw_xml = envios
        transmision_de._sign_xml = firmador
        transmision_de._serialize = Registrador(_rde_sifen(_cdc_ficticio(21)))

        resultado = transmision_de.enviar_de(object(), sign=False)

        assert firmador.veces == 0
        assert envios.veces == 1
        assert isinstance(resultado, RRetEnviDe)

    def test_enviar_de_xml_envia_xml_ya_firmado(self, transmision_de: Any) -> None:
        """L22."""
        envios = Registrador(RRetEnviDe(rProtDe=RProtDe(dFecProc=FECHA_PROCESO)))
        transmision_de._send_raw_xml = envios

        resultado = transmision_de.enviar_de_xml(f'<rDE xmlns="{NS_SIFEN}"/>'.encode())

        assert isinstance(resultado, RRetEnviDe)
        servicio, solicitud = envios.argumentos[0]
        assert servicio == "recep_de"
        assert b"<xDE>" in solicitud
        assert b"<rDE" in solicitud

    def test_enviar_de_pasa_xml_serializado_y_cdc_al_firmador(
        self,
        transmision_de: Any,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N49."""
        cdc = _cdc_ficticio(49)
        serializado = _rde_sifen(cdc)
        firmador = Registrador(serializado)
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador(serializado))
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        transmision_de._send_raw_xml = Registrador(_ret_envi_de_minimo())

        transmision_de.enviar_de(rde_simulado(cdc))

        assert firmador.llamadas == [((serializado, cdc), {})]

    @pytest.mark.parametrize(
        "rde",
        [
            pytest.param(SimpleNamespace(), id="sin_atributo_DE"),
            pytest.param(SimpleNamespace(DE=SimpleNamespace(Id=None)), id="id_none"),
            pytest.param(SimpleNamespace(DE=SimpleNamespace(Id="")), id="id_vacio"),
        ],
    )
    def test_enviar_de_sin_id_no_firma(
        self, transmision_de: Any, monkeypatch: pytest.MonkeyPatch, rde: Any
    ) -> None:
        """N50."""
        firmador = Registrador()
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        monkeypatch.setattr(
            TransmisionBase, "_serialize", Registrador(_rde_sifen(_cdc_ficticio(50)))
        )
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios

        transmision_de.enviar_de(rde, sign=True)

        assert firmador.veces == 0
        assert envios.veces == 1

    def test_enviar_de_con_de_nulo_propaga_attribute_error(
        self, transmision_de: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador("<rDE/>"))
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios
        with pytest.raises(AttributeError):
            transmision_de.enviar_de(SimpleNamespace(DE=None))
        assert envios.veces == 0

    def test_solicitud_renvide_tiene_la_estructura_sifen(
        self, transmision_de: Any
    ) -> None:
        """N51."""
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios

        transmision_de.enviar_de_xml(_rde_sifen(_cdc_ficticio(51)))

        solicitud = envios.argumentos[0][1]
        assert re.match(
            rb"<\?xml[^>]*encoding=[\"']utf-8[\"']", solicitud, flags=re.IGNORECASE
        )
        raiz = etree.fromstring(solicitud)
        assert raiz.tag == f"{{{NS_SIFEN}}}rEnviDe"
        assert raiz.prefix is None
        assert [hijo.tag for hijo in raiz] == [
            f"{{{NS_SIFEN}}}dId",
            f"{{{NS_SIFEN}}}xDE",
        ]
        assert raiz[0].text.isdigit()
        contenido = list(raiz[1])
        assert [elemento.tag for elemento in contenido] == [f"{{{NS_SIFEN}}}rDE"]
        assert (
            contenido[0].get(f"{{{NS_XSI}}}schemaLocation") == SCHEMA_LOCATION_RECEPCION
        )

    def test_schema_location_existente_se_respeta(self, transmision_de: Any) -> None:
        """N52."""
        propio = f"{NS_SIFEN} esquema_local_de_prueba.xsd"
        entrada = (
            f'<rDE xmlns="{NS_SIFEN}" xmlns:xsi="{NS_XSI}" '
            f'xsi:schemaLocation="{propio}"><DE Id="{_cdc_ficticio(52)}"/></rDE>'
        )
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios

        transmision_de.enviar_de_xml(entrada)

        rde = _rde_dentro_de_solicitud(envios.argumentos[0][1])
        assert rde.get(f"{{{NS_XSI}}}schemaLocation") == propio

    def test_build_enviar_de_request_xml_contrato_infraestructura(self) -> None:
        """N53."""
        cdc = _cdc_ficticio(53)
        firmado = '<?xml version="1.0" encoding="UTF-8"?>\n' + _rde_sifen(
            cdc,
            f'<Signature xmlns="{NS_XMLDSIG}"><SignedInfo/>'
            "<SignatureValue>QUJD</SignatureValue></Signature>",
        )

        solicitud = _build_enviar_de_request_xml(1, firmado)

        assert isinstance(solicitud, bytes)
        texto = solicitud.decode("utf-8")
        assert texto.startswith("<?xml")
        assert texto.count("<?xml") == 1
        raiz = etree.fromstring(solicitud)
        assert raiz.find(f"{{{NS_SIFEN}}}dId").text == "1"
        rde = _rde_dentro_de_solicitud(solicitud)
        assert rde.find(f"{{{NS_SIFEN}}}DE").get("Id") == cdc
        assert rde.find(f"{{{NS_XMLDSIG}}}Signature") is not None

    def test_enviar_de_xml_no_firma_ni_serializa_y_conserva_firma(
        self, transmision_de: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N54."""
        firmador = Registrador()
        serializador = Registrador()
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        monkeypatch.setattr(TransmisionBase, "_serialize", serializador)
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios
        entrada = _rde_sifen(
            _cdc_ficticio(54),
            f'<Signature xmlns="{NS_XMLDSIG}"><SignedInfo/>'
            "<SignatureValue>WFla</SignatureValue></Signature>",
        )

        transmision_de.enviar_de_xml(entrada)

        assert firmador.veces == 0
        assert serializador.veces == 0
        rde = _rde_dentro_de_solicitud(envios.argumentos[0][1])
        firma = rde.find(f"{{{NS_XMLDSIG}}}Signature")
        assert firma is not None
        assert firma.find(f"{{{NS_XMLDSIG}}}SignatureValue").text == "WFla"

    @pytest.mark.parametrize("como_bytes", [False, True], ids=["str", "bytes"])
    def test_enviar_de_xml_acepta_texto_y_bytes(
        self, transmision_de: Any, como_bytes: bool
    ) -> None:
        """N55: la solicitud es la misma salvo el ``dId``."""
        texto = _rde_sifen(_cdc_ficticio(55))
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios

        transmision_de.enviar_de_xml(texto.encode("utf-8") if como_bytes else texto)

        solicitud = envios.argumentos[0][1]
        d_id = int(etree.fromstring(solicitud).find(f"{{{NS_SIFEN}}}dId").text)
        assert solicitud == _build_enviar_de_request_xml(d_id, texto)

    def test_enviar_de_xml_malformado_no_envia(self, transmision_de: Any) -> None:
        """N56."""
        envios = Registrador(_ret_envi_de_minimo())
        transmision_de._send_raw_xml = envios
        with pytest.raises(etree.XMLSyntaxError):
            transmision_de.enviar_de_xml(f'<rDE xmlns="{NS_SIFEN}"><DE Id="1">')
        assert envios.veces == 0

    def test_enviar_de_respuesta_en_bytes_se_parsea(
        self,
        transmision_de: Any,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N57."""
        cdc = _cdc_ficticio(57)
        respuesta = (
            f'<p:rRetEnviDe xmlns:p="{NS_SIFEN}"><p:rProtDe><p:Id>{cdc}</p:Id>'
            f"<p:dFecProc>{FECHA_PROCESO}</p:dFecProc>"
            "<p:dEstRes>Aprobado con observacion</p:dEstRes>"
            "<p:gResProc><p:dCodRes>1005</p:dCodRes>"
            "<p:dMsgRes>Observacion ficticia</p:dMsgRes></p:gResProc>"
            "</p:rProtDe></p:rRetEnviDe>"
        ).encode("utf-8")
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador(_rde_sifen(cdc)))
        transmision_de._send_raw_xml = Registrador(respuesta)

        resultado = transmision_de.enviar_de(rde_simulado(cdc), sign=False)

        assert isinstance(resultado, RRetEnviDe)
        assert resultado.rProtDe.Id == cdc
        assert resultado.rProtDe.dFecProc == FECHA_PROCESO
        assert resultado.rProtDe.dEstRes == "Aprobado con observacion"
        assert resultado.rProtDe.gResProc[0].dCodRes == "1005"
        assert resultado.rProtDe.gResProc[0].dMsgRes == "Observacion ficticia"

    def test_enviar_de_sobre_ajeno_no_reenvia(self, transmision_de: Any) -> None:
        """N58: un DE nunca se reenvia automaticamente; el sobre ajeno deja el
        resultado incierto."""
        envios = Registrador(RESPUESTA_RUC_0502)
        transmision_de._send_raw_xml = envios
        with pytest.raises(SifenUnexpectedResponseError) as error:
            transmision_de.enviar_de_xml(_rde_sifen(_cdc_ficticio(58)))
        assert isinstance(error.value, SifenTransportError)
        assert error.value.expected_root == "rRetEnviDe"
        assert error.value.actual_root == "rResEnviConsRUC"
        assert error.value.code == "0502"
        assert error.value.raw_body == RESPUESTA_RUC_0502.decode("utf-8")
        assert envios.veces == 1

    @pytest.mark.parametrize(
        "falla, es_timeout",
        [
            pytest.param(
                requests.exceptions.Timeout("sin respuesta del SIFEN"),
                True,
                id="timeout",
            ),
            pytest.param(RespuestaHttpFalsa(b"", 503), False, id="http_503"),
        ],
    )
    @pytest.mark.parametrize(
        "enviar_con_valores_por_defecto",
        [
            pytest.param(_enviar_de_xml_por_defecto, id="enviar_de_xml"),
            pytest.param(_enviar_evento_crudo_por_defecto, id="evento_crudo"),
        ],
    )
    def test_transmision_por_defecto_no_reenvia_tras_timeout(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
        enviar_con_valores_por_defecto: Callable[[dict[str, Any]], Any],
        falla: Any,
        es_timeout: bool,
    ) -> None:
        """N59: una mutacion con ``max_retries`` por defecto hace un solo POST."""
        red = red_simulada(falla)
        with pytest.raises(SifenTransportError) as error:
            enviar_con_valores_por_defecto(credenciales_ficticias)
        assert isinstance(error.value, SifenTimeoutError) is es_timeout
        assert len(red.llamadas) == 1

    def test_enviar_lote_acepta_exactamente_cincuenta(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N60."""
        cliente_soap_falso.respuesta = RResEnviLoteDe(dCodRes="0300")
        firmador = Registrador(efecto=lambda _xml, doc_id: _rde_lote(doc_id))
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador("<rDE/>"))
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        documentos = [rde_simulado(_cdc_ficticio(600 + n)) for n in range(MAX_LOTE)]

        transmision_de.enviar_lote(documentos)

        assert firmador.veces == 50
        _nombres, contenido = _abrir_zip_lote(cliente_soap_falso.envios[0].xDE)
        assert contenido.count(b"<rDE ") == MAX_LOTE

    @pytest.mark.parametrize(
        "cantidad, fragmento",
        [(MAX_LOTE + 1, "como maximo 50"), (0, "al menos un documento")],
        ids=["51", "0"],
    )
    def test_enviar_lote_valida_antes_de_procesar(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
        cantidad: int,
        fragmento: str,
    ) -> None:
        """N61."""
        serializador = Registrador("<rDE/>")
        firmador = Registrador("<rDE/>")
        monkeypatch.setattr(TransmisionBase, "_serialize", serializador)
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        documentos = [rde_simulado(_cdc_ficticio(n)) for n in range(cantidad)]
        with pytest.raises(ValueError, match=fragmento):
            transmision_de.enviar_lote(documentos)
        assert serializador.veces == 0
        assert firmador.veces == 0
        assert cliente_soap_falso.servicios == []

    def test_enviar_lote_payload_zip_y_did(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N62: el ``xDE`` del binding son los bytes de un ZIP con el lote."""

        def firmar(xml: str, doc_id: str) -> str:
            return _rde_lote(doc_id, extra=f"<firma>ñ-{doc_id[-2:]}</firma>")

        cliente_soap_falso.respuesta = RResEnviLoteDe(dCodRes="0300")
        monkeypatch.setattr(TransmisionBase, "_serialize", Registrador("<rDE/>"))
        monkeypatch.setattr(TransmisionBase, "_sign_xml", Registrador(efecto=firmar))
        identificadores = [_cdc_ficticio(n) for n in (621, 622, 623, 624)]

        transmision_de.enviar_lote(
            [rde_simulado(cdc) for cdc in identificadores], lote_id=5150
        )

        assert cliente_soap_falso.servicios == ["recep_lote"]
        (envio,) = cliente_soap_falso.envios
        assert isinstance(envio, REnvioLote)
        assert envio.dId == 5150
        assert envio.xDE.startswith(b"PK")
        nombres, contenido = _abrir_zip_lote(envio.xDE)
        assert nombres == [NOMBRE_ARCHIVO_LOTE]
        raiz = etree.fromstring(contenido)
        assert raiz.tag == "rLoteDE"
        assert [rde.find(f"{{{NS_SIFEN}}}DE").get("Id") for rde in raiz] == (
            identificadores
        )
        assert "ñ-24".encode() in contenido

    def test_enviar_lote_base64_una_sola_vez_en_el_cable(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
    ) -> None:
        """El binding codifica el ZIP en base64 una sola vez (antes eran dos)."""
        cliente_soap_falso.respuesta = RResEnviLoteDe(dCodRes="0300")
        documentos = [_rde_lote(_cdc_ficticio(n)) for n in (651, 652)]

        transmision_de.enviar_lote_xml(documentos, lote_id=7)

        (envio,) = cliente_soap_falso.envios
        assert envio.dId == 7
        assert envio.xDE == _build_lote_zip(documentos)
        cable = ET.fromstring(_xml_de_binding(envio).encode("utf-8"))
        assert base64.b64decode(_hijo_local(cable, "xDE").text) == envio.xDE

    @pytest.mark.parametrize("lote_id", [None, 0], ids=["None", "cero"])
    def test_enviar_lote_sin_lote_id_genera_identificador(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
        lote_id: int | None,
    ) -> None:
        """N63."""
        cliente_soap_falso.respuesta = RResEnviLoteDe(dCodRes="0300")
        monkeypatch.setattr(
            TransmisionBase, "_serialize", Registrador(efecto=_rde_lote_de_binding)
        )

        transmision_de.enviar_lote(
            [rde_simulado(_cdc_ficticio(631))], lote_id=lote_id, sign=False
        )

        (envio,) = cliente_soap_falso.envios
        assert isinstance(envio.dId, int)
        assert envio.dId > 0

    def test_enviar_lote_sin_firma(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        rde_simulado: Callable[[Any], SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N64."""
        cliente_soap_falso.respuesta = RResEnviLoteDe(dCodRes="0300")
        firmador = Registrador()
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        monkeypatch.setattr(
            TransmisionBase, "_serialize", Registrador(efecto=_rde_lote_de_binding)
        )
        identificadores = [_cdc_ficticio(n) for n in (641, 642)]

        transmision_de.enviar_lote(
            [rde_simulado(cdc) for cdc in identificadores], sign=False
        )

        assert firmador.veces == 0
        _nombres, contenido = _abrir_zip_lote(cliente_soap_falso.envios[0].xDE)
        for cdc in identificadores:
            assert f'<DE Id="{cdc}">'.encode() in contenido

    @pytest.mark.parametrize("d_id, xml_de, esperado", CASOS_SOLICITUD_DORADOS)
    def test_build_enviar_de_request_xml_ejemplos_dorados(
        self, d_id: Any, xml_de: str, esperado: bytes
    ) -> None:
        assert _build_enviar_de_request_xml(d_id, xml_de) == esperado

    def test_build_enviar_de_request_xml_es_determinista(self) -> None:
        entrada = _rde_sifen(_cdc_ficticio(115))
        assert _build_enviar_de_request_xml(
            d_id=8, xml_de=entrada
        ) == _build_enviar_de_request_xml(8, entrada)

    def test_build_enviar_de_request_xml_mal_formado(self) -> None:
        with pytest.raises(etree.XMLSyntaxError):
            _build_enviar_de_request_xml(1, "no xml")

    @pytest.mark.parametrize(
        "armar_solicitud",
        [
            pytest.param(_solicitud_por_constructor, id="constructor"),
            pytest.param(_solicitud_por_enviar_de_xml, id="enviar_de_xml"),
        ],
    )
    def test_firma_sigue_valida_dentro_de_renvide(
        self,
        pfx_de_prueba: bytes,
        transmision_de: Any,
        armar_solicitud: Callable[[Any, str], bytes],
    ) -> None:
        """N72."""
        cdc = _cdc_ficticio(72)
        firmado = _firmar_con_pfx(pfx_de_prueba, _rde_sifen(cdc), cdc)

        solicitud = armar_solicitud(transmision_de, firmado)

        _verificar_firma(
            _rde_dentro_de_solicitud(solicitud), _certificado_pem(pfx_de_prueba)
        )

    @pytest.mark.parametrize(
        "armar_solicitud",
        [
            pytest.param(_solicitud_por_constructor, id="constructor"),
            pytest.param(_solicitud_por_enviar_de_xml, id="enviar_de_xml"),
        ],
    )
    def test_firma_de_rde_prefijado_dentro_de_renvide(
        self,
        pfx_de_prueba: bytes,
        transmision_de: Any,
        armar_solicitud: Callable[[Any, str], bytes],
    ) -> None:
        """N73 (defecto P3 corregido): el rDE prefijado se inserta sin
        reexpresarlo y la firma sigue verificando."""
        cdc = _cdc_ficticio(73)
        prefijado = (
            f'<s:rDE xmlns:s="{NS_SIFEN}"><s:dVerFor>150</s:dVerFor>'
            f'<s:DE Id="{cdc}"><s:dDVId>4</s:dDVId></s:DE></s:rDE>'
        )
        firmado = _firmar_con_pfx(pfx_de_prueba, prefijado, cdc)

        solicitud = armar_solicitud(transmision_de, firmado)

        rde = _rde_dentro_de_solicitud(solicitud)
        assert rde.prefix == "s"
        assert rde.find(f"{{{NS_SIFEN}}}DE").prefix == "s"
        certificado = _certificado_pem(pfx_de_prueba)
        _verificar_firma(rde, certificado)
        _verificar_firma_en_solicitud(solicitud, certificado)

    @pytest.mark.parametrize(
        "armar_solicitud",
        [
            pytest.param(_solicitud_por_constructor, id="constructor"),
            pytest.param(_solicitud_por_enviar_de_xml, id="enviar_de_xml"),
        ],
    )
    def test_binding_firmado_con_prefijos_xsdata_verifica_en_renvide(
        self,
        pfx_de_prueba: bytes,
        transmision_de: Any,
        armar_solicitud: Callable[[Any, str], bytes],
    ) -> None:
        """``BindingMixin.sign_xml`` firma la serializacion de xsdata, que usa
        el prefijo ``ns0:``; ese rDE firmado tambien verifica dentro de
        ``rEnviDe``."""
        rde_binding = RDe.from_path(FACTURA.ruta)
        firmado = rde_binding.sign_xml(
            None, pfx_de_prueba, CONTRASENA_CERTIFICADO_PRUEBA, FACTURA.cdc
        )
        assert "<ns0:rDE" in firmado

        solicitud = armar_solicitud(transmision_de, firmado)

        certificado = _certificado_pem(pfx_de_prueba)
        _verificar_firma(_rde_dentro_de_solicitud(solicitud), certificado)
        _verificar_firma_en_solicitud(solicitud, certificado)

    def test_enviar_de_firma_un_binding_sin_prefijos_y_verifica_en_renvide(
        self, pfx_de_prueba: bytes
    ) -> None:
        """``enviar_de(rde)`` serializa el rDE con el namespace del SIFEN por
        defecto, lo firma y la firma verifica dentro de ``rEnviDe``."""
        envios = Registrador(_ret_envi_de_minimo())
        with TransmisionDE(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            transmision._send_raw_xml = envios
            transmision.enviar_de(RDe.from_path(FACTURA.ruta))

        ((servicio, solicitud),) = envios.argumentos
        assert servicio == "recep_de"
        assert not re.search(rb"<\w+:", solicitud)
        rde = _rde_dentro_de_solicitud(solicitud)
        assert rde.find(f"{{{NS_SIFEN}}}DE").get("Id") == FACTURA.cdc
        assert len(rde.findall(f"{{{NS_XMLDSIG}}}Signature")) == 1
        certificado = _certificado_pem(pfx_de_prueba)
        _verificar_firma(rde, certificado)
        _verificar_firma_en_solicitud(solicitud, certificado)

    def test_enviar_de_serializa_con_el_namespace_por_defecto(
        self, transmision_de: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serializaciones = Registrador(_rde_sifen(_cdc_ficticio(74)))
        monkeypatch.setattr(TransmisionBase, "_serialize", serializaciones)
        transmision_de._send_raw_xml = Registrador(_ret_envi_de_minimo())
        rde = SimpleNamespace(DE=SimpleNamespace(Id=""))

        transmision_de.enviar_de(rde)

        assert serializaciones.llamadas == [((rde,), {"ns_map": {None: NS_SIFEN}})]


# ---------------------------------------------------------------------------
# Lote asincrono: formato oficial (MT v150 sec. 7.2 y 9.2; Guia oct-2024)
# ---------------------------------------------------------------------------

_DECLARACION_LOTE = b'<?xml version="1.0" encoding="UTF-8"?>'


def _cuerpo_lote_recibido() -> str:
    """``rResEnviLoteDe`` 0300 con prefijo propio, como responde el SIFEN."""
    return (
        f'<l:rResEnviLoteDe xmlns:l="{NS_SIFEN}">'
        f"<l:dFecProc>{FECHA_PROCESO}</l:dFecProc><l:dCodRes>0300</l:dCodRes>"
        "<l:dMsgRes>Lote recibido con exito</l:dMsgRes>"
        f"<l:dProtConsLote>{PROTOCOLO_LOTE}</l:dProtConsLote>"
        "<l:dTpoProces>0</l:dTpoProces></l:rResEnviLoteDe>"
    )


def _xde_en_el_cable(solicitud: bytes) -> bytes:
    """Bytes de ``xDE`` decodificados UNA vez desde el sobre SOAP enviado."""
    raiz = etree.fromstring(solicitud)
    xde = raiz.find(f".//{{{NS_SIFEN}}}xDE")
    assert xde is not None, "la solicitud no contiene rEnvioLote/xDE"
    return base64.b64decode(xde.text, validate=True)


class TestLoteFormatoOficial:
    def test_zip_con_una_entrada_y_una_sola_declaracion(self) -> None:
        """MT sec. 7.2.1 y 9.2.1; Guia pp. 8-9: ZIP de un XML ``rLoteDE``."""
        primero = _rde_lote(_cdc_ficticio(801))
        segundo = '<?xml version="1.0" encoding="UTF-8"?>\n' + _rde_lote(
            _cdc_ficticio(802)
        )

        datos = _build_lote_zip([primero, segundo])

        with zipfile.ZipFile(io.BytesIO(datos)) as archivo:
            (entrada,) = archivo.infolist()
            assert entrada.filename == NOMBRE_ARCHIVO_LOTE
            assert entrada.filename.endswith(".xml")
            assert entrada.compress_type == zipfile.ZIP_DEFLATED
            contenido = archivo.read(entrada)
        assert contenido.startswith(_DECLARACION_LOTE + b"<rLoteDE><rDE ")
        assert contenido.endswith(b"</rDE></rLoteDE>")
        assert contenido.count(b"<?xml") == 1
        assert re.search(rb">\s+<", contenido) is None

    def test_rlotede_sin_namespace_y_cada_rde_con_el_suyo(self) -> None:
        """MT sec. 7.2.2.2: cada ``rDE`` declara su namespace; Guia p. 8."""
        identificadores = [_cdc_ficticio(n) for n in (811, 812, 813)]

        _nombres, contenido = _abrir_zip_lote(
            _build_lote_zip([_rde_lote(cdc) for cdc in identificadores])
        )

        raiz = etree.fromstring(contenido)
        assert raiz.tag == "rLoteDE"
        assert raiz.nsmap == {}
        assert len(raiz) == len(identificadores)
        for rde, cdc in zip(raiz, identificadores):
            assert rde.tag == f"{{{NS_SIFEN}}}rDE"
            assert rde.nsmap[None] == NS_SIFEN
            assert rde.get(f"{{{NS_XSI}}}schemaLocation") == (
                f"{NS_SIFEN} siRecepDE_v150.xsd"
            )
            assert rde.find(f"{{{NS_SIFEN}}}DE").get("Id") == cdc
        apertura = f'<rDE xmlns="{NS_SIFEN}" xmlns:xsi="{NS_XSI}"'.encode()
        assert contenido.count(apertura) == len(identificadores)

    def test_zip_determinista(self) -> None:
        documentos = [_rde_lote(_cdc_ficticio(n)) for n in (821, 822)]
        assert _build_lote_zip(documentos) == _build_lote_zip(list(documentos))

    @pytest.mark.parametrize(
        "segundo, fragmento",
        [
            pytest.param(
                _rde_lote(_cdc_ficticio(832), tipo=NOTA_CREDITO.tipo),
                "un solo tipo de DE",
                id="tipos_distintos",
            ),
            pytest.param(
                _rde_lote(_cdc_ficticio(832), ruc=FACTURA.ruc_receptor),
                "un solo RUC emisor",
                id="ruc_distintos",
            ),
            pytest.param(
                _rde_lote(_cdc_ficticio(831)),
                "no puede repetirse",
                id="cdc_repetido",
            ),
        ],
    )
    def test_composicion_invalida_no_se_envia(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        segundo: str,
        fragmento: str,
    ) -> None:
        """MT sec. 9.2.2; Guia p. 6 (causas a y b de 0301) y p. 7 (causa g)."""
        with pytest.raises(ValueError, match=fragmento):
            transmision_de.enviar_lote_xml([_rde_lote(_cdc_ficticio(831)), segundo])
        assert cliente_soap_falso.envios == []

    @pytest.mark.parametrize(
        "documento, fragmento",
        [
            pytest.param(
                _rde_lote(_cdc_ficticio(841)).replace("><DE", ">\n  <DE"),
                "blancos entre etiquetas",
                id="salto_de_linea",
            ),
            pytest.param(
                _rde_lote(_cdc_ficticio(841)).replace("</gTimb>", "</gTimb>\t"),
                "blancos entre etiquetas",
                id="tab",
            ),
            pytest.param(
                f'<rDE xmlns="{NS_SIFEN}"><dVerFor>150</dVerFor></rDE>',
                "DE con Id",
                id="sin_de",
            ),
            pytest.param(
                _rde_lote(_cdc_ficticio(841)).replace("<iTiDE>1</iTiDE>", ""),
                "iTiDE",
                id="sin_tipo",
            ),
            pytest.param(
                _rde_lote(_cdc_ficticio(841)).replace(
                    f"<dRucEm>{FACTURA.ruc_emisor}</dRucEm>", ""
                ),
                "dRucEm",
                id="sin_ruc",
            ),
            pytest.param(
                _rde_lote(_cdc_ficticio(841)).replace(f' xmlns="{NS_SIFEN}"', ""),
                "no es un rDE del SIFEN",
                id="sin_namespace",
            ),
        ],
    )
    def test_documento_invalido_no_se_envia(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        documento: str,
        fragmento: str,
    ) -> None:
        """Un lote con contenido no valido bloquea el RUC (Guia p. 7, causa f)."""
        with pytest.raises(ValueError, match=fragmento):
            transmision_de.enviar_lote_xml([documento])
        assert cliente_soap_falso.envios == []

    @pytest.mark.parametrize(
        "cantidad, fragmento",
        [(MAX_LOTE + 1, "como maximo 50"), (0, "al menos un documento")],
        ids=["51", "0"],
    )
    def test_enviar_lote_xml_valida_la_cantidad(
        self,
        transmision_de: Any,
        cliente_soap_falso: ClienteSoapFalso,
        cantidad: int,
        fragmento: str,
    ) -> None:
        documentos = [_rde_lote(_cdc_ficticio(850 + n)) for n in range(cantidad)]
        with pytest.raises(ValueError, match=fragmento):
            transmision_de.enviar_lote_xml(documentos)
        assert cliente_soap_falso.envios == []

    def test_tope_de_1000_kb_sobre_el_mensaje_completo(
        self,
        credenciales_ficticias: dict[str, Any],
        red_simulada: Callable[..., RedSimulada],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Guia p. 6 (causa e de 0301): se mide el sobre SOAP que se envia."""
        assert MAX_BYTES_MENSAJE_LOTE == 1_000_000
        documentos = [_rde_lote(_cdc_ficticio(861))]
        red = red_simulada(
            RespuestaHttpFalsa(_sobre_soap12(_cuerpo_lote_recibido()))
        )
        with TransmisionDE(**credenciales_ficticias) as transmision:
            transmision.enviar_lote_xml(documentos, lote_id=861)
        tamano_en_el_cable = len(red.llamadas[0].data)

        monkeypatch.setattr(
            modulo_de, "MAX_BYTES_MENSAJE_LOTE", tamano_en_el_cable - 1
        )
        with TransmisionDE(**credenciales_ficticias) as transmision:
            with pytest.raises(ValueError, match="1000 KB"):
                transmision.enviar_lote_xml(documentos, lote_id=861)
        assert len(red.llamadas) == 1

        monkeypatch.setattr(modulo_de, "MAX_BYTES_MENSAJE_LOTE", tamano_en_el_cable)
        with TransmisionDE(**credenciales_ficticias) as transmision:
            transmision.enviar_lote_xml(documentos, lote_id=861)
        assert len(red.llamadas) == 2

    def test_cable_lleva_el_zip_en_base64_una_sola_vez_y_la_firma_verifica(
        self,
        pfx_de_prueba: bytes,
        red_simulada: Callable[..., RedSimulada],
    ) -> None:
        """De punta a punta: binding real firmado, cliente xsdata y transporte
        reales; solo el POST es simulado."""
        red = red_simulada(
            RespuestaHttpFalsa(_sobre_soap12(_cuerpo_lote_recibido()))
        )
        with TransmisionDE(
            ambiente=TEST,
            pkcs12_data=pfx_de_prueba,
            pkcs12_password=CONTRASENA_CERTIFICADO_PRUEBA,
        ) as transmision:
            respuesta = transmision.enviar_lote(
                [RDe.from_path(FACTURA.ruta)], lote_id=870
            )

        assert respuesta.dCodRes == "0300"
        assert respuesta.dProtConsLote == PROTOCOLO_LOTE
        (llamada,) = red.llamadas
        assert llamada.url == get_endpoint(TEST, "recep_lote")
        datos_zip = _xde_en_el_cable(llamada.data)
        assert datos_zip.startswith(b"PK\x03\x04")
        nombres, contenido = _abrir_zip_lote(datos_zip)
        assert nombres == [NOMBRE_ARCHIVO_LOTE]
        assert contenido.startswith(_DECLARACION_LOTE + b"<rLoteDE><rDE ")
        assert re.search(rb">\s+<", contenido) is None
        assert not re.search(rb"<\w+:", contenido)
        (rde,) = etree.fromstring(contenido)
        assert rde.find(f"{{{NS_SIFEN}}}DE").get("Id") == FACTURA.cdc
        _verificar_firma(rde, _certificado_pem(pfx_de_prueba))


# ---------------------------------------------------------------------------
# Eventos (TransmisionEvento)
# ---------------------------------------------------------------------------


class TestTransmisionEvento:
    def test_enviar_evento_devuelve_resultado_procesado(
        self, transmision_evento: Any, cliente_soap_falso: ClienteSoapFalso
    ) -> None:
        """L36."""
        cliente_soap_falso.respuesta = RRetEnviEventoDe(
            dFecProc=FECHA_PROCESO,
            gResProcEVe=[
                TgResProcEve(
                    dEstRes="Aprobado",
                    dProtAut=6170033451,
                    id="36",
                    gResProc=[TgResProc(dCodRes="0460", dMsgRes="Evento registrado")],
                )
            ],
        )
        resultado = transmision_evento.enviar_evento(SimpleNamespace())
        assert isinstance(resultado, RRetEnviEventoDe)
        assert resultado.gResProcEVe[0].dEstRes == "Aprobado"
        assert resultado.gResProcEVe[0].dProtAut == 6170033451

    def test_enviar_evento_envuelve_grupo_en_renvieventode(
        self,
        transmision_evento: Any,
        cliente_soap_falso: ClienteSoapFalso,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N65; el evento no se firma aqui."""
        firmador = Registrador()
        monkeypatch.setattr(TransmisionBase, "_sign_xml", firmador)
        cliente_soap_falso.respuesta = RRetEnviEventoDe(dFecProc=FECHA_PROCESO)
        evento = SimpleNamespace(descripcion="grupo de eventos ficticio")

        transmision_evento.enviar_evento(evento)

        assert cliente_soap_falso.servicios == ["evento"]
        (envio,) = cliente_soap_falso.envios
        assert isinstance(envio, REnviEventoDe)
        assert isinstance(envio.dId, int)
        assert envio.dId > 0
        assert isinstance(envio.dEvReg, REnviEventoDe.DEvReg)
        assert envio.dEvReg.gGroupGesEve is evento
        assert firmador.veces == 0

    def test_send_raw_xml_devuelve_bytes_del_transporte(
        self, transmision_evento: Any
    ) -> None:
        """N66."""
        transporte_falso = TransporteFalso()
        transporte_falso.respuesta = b"<rRetEnviEventoDe>ok</rRetEnviEventoDe>"
        transmision_evento._get_transport = lambda: transporte_falso

        resultado = transmision_evento._send_raw_xml("evento", "<x/>")

        assert resultado == b"<rRetEnviEventoDe>ok</rRetEnviEventoDe>"
        ((args, kwargs),) = transporte_falso.envios
        assert args[0] == get_endpoint(TEST, "evento")
        enviado = kwargs["data"] if "data" in kwargs else args[1]
        assert enviado == "<x/>"
        # Sin cabeceras propias: el transporte aplica las suyas por defecto.
        assert set(kwargs) <= {"data"}
        assert len(args) <= 2

    def test_evento_crudo_como_context_manager(
        self,
        credenciales_ficticias: dict[str, Any],
        fabricas_falsas: FabricasFalsas,
    ) -> None:
        """Camino de la plataforma: ``with`` + ``_send_raw_xml("evento", str)``."""
        with TransmisionEvento(**credenciales_ficticias) as transmision:
            resultado = transmision._send_raw_xml(
                "evento",
                f"<rEnviEventoDe xmlns='{NS_SIFEN}'><dId>3</dId></rEnviEventoDe>",
            )
        (transporte_falso,) = fabricas_falsas.transportes
        assert resultado == transporte_falso.respuesta
        assert transmision._closed is True
        assert transporte_falso.cierres == 1

    def test_generate_id_de_evento_es_entero_de_hasta_15_digitos(self) -> None:
        """N67."""
        identificador = modulo_evento._generate_id()
        assert isinstance(identificador, int)
        assert 0 <= identificador < 10**15

    def test_generate_id_deriva_del_reloj_en_milisegundos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instante = 1_791_234_567.891
        monkeypatch.setattr(time, "time", lambda: instante)
        assert (
            modulo_evento._generate_id() == int(instante * 1000) % 999_999_999_999_999
        )
