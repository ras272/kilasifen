"""Envio de Documentos Electronicos (DE) al SIFEN, uno a uno o por lote."""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from kilasifen.engine.de.bindings.v150.ws_si_recep_de_v150 import RRetEnviDe
from kilasifen.engine.de.bindings.v150.ws_si_recep_lote_de_v141 import (
    REnvioLote,
    RResEnviLoteDe,
)
from kilasifen.engine.transmision.base import (
    TransmisionBase,
    _generate_id,
    _importar_opcional,
    _serializador,
    _wrap_soap_envelope,
)

__all__ = [
    "MAX_BYTES_MENSAJE_LOTE",
    "MAX_LOTE",
    "NOMBRE_ARCHIVO_LOTE",
    "TransmisionDE",
]

#: Cantidad maxima de documentos que admite un lote (MT v150 sec. 9.2.1, p. 47;
#: Guia de mejores practicas, oct-2024, p. 6, causa c de 0301).
MAX_LOTE: int = 50

#: Tope del mensaje de entrada de ``recibe-lote``: 1000 KB (Guia de mejores
#: practicas, oct-2024, p. 6, causa e de 0301). El MT (sec. 12.3.2.1, p. 155) fija
#: 10.000 KB y la Guia no dice si un KB son 1000 o 1024 bytes (NO
#: DETERMINADO): se usa la lectura mas restrictiva, 1.000.000 bytes del sobre
#: SOAP completo.
MAX_BYTES_MENSAJE_LOTE: int = 1_000_000

#: Nombre de la unica entrada del ZIP del lote. Ni el MT ni la Guia lo fijan
#: (NO DETERMINADO); solo se exige que el archivo sea XML.
NOMBRE_ARCHIVO_LOTE: str = "lote.xml"

_NS_SIFEN = "http://ekuatia.set.gov.py/sifen/xsd"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_ATRIBUTO_SCHEMA_LOCATION = f"{{{_NS_XSI}}}schemaLocation"
_SCHEMA_LOCATION_RECEPCION = f"{_NS_SIFEN} siRecepDE_v150.xsd"

#: Unica declaracion XML del archivo del lote (MT v150 sec. 7.2.1, p. 30).
_DECLARACION_LOTE = '<?xml version="1.0" encoding="UTF-8"?>'

#: ``rLoteDE`` va sin namespace, como en el ejemplo de la Guia de mejores
#: practicas (oct-2024, pp. 8-9); cada ``rDE`` declara el suyo (MT v150
#: sec. 7.2.2.2, pp. 31-32). No hay XSD publicado de ``rLoteDE``.
_APERTURA_LOTE = "<rLoteDE>"
_CIERRE_LOTE = "</rLoteDE>"

#: Fecha fija de la entrada del ZIP, para que el mismo lote produzca siempre
#: los mismos bytes. Ninguna fuente oficial pide una fecha.
_FECHA_ENTRADA_ZIP = (1980, 1, 1, 0, 0, 0)

#: Rutas, relativas al ``rDE``, de los datos que identifican cada documento
#: del lote. ``_S`` es el prefijo ``{namespace}`` del SIFEN en notacion de
#: lxml.
_S = f"{{{_NS_SIFEN}}}"
_ETIQUETA_RDE = f"{_S}rDE"
_RUTA_DE = f"{_S}DE"
_RUTA_TIPO_DE = f"{_S}DE/{_S}gTimb/{_S}iTiDE"
_RUTA_RUC_EMISOR = f"{_S}DE/{_S}gDatGralOpe/{_S}gEmis/{_S}dRucEm"

#: Prefijos con que se serializa un ``rDE``: el namespace del SIFEN queda como
#: espacio por defecto, sin prefijo, como en el XML que arma la plataforma.
_NS_MAP_RDE: dict[str | None, str] = {None: _NS_SIFEN}

#: Apertura del request ``rEnviDe``, igual a la que produce lxml.
_APERTURA_RENVIDE = (
    f"<?xml version='1.0' encoding='UTF-8'?>\n<rEnviDe xmlns=\"{_NS_SIFEN}\">"
)

#: Marca de "el binding no tiene atributo DE".
_SIN_DE = object()


def _with_schema_location(xml_de: str | bytes) -> Any:
    """Parsea el ``rDE`` con lxml y le asegura un ``xsi:schemaLocation``.

    Si el elemento raiz ya declara ``xsi:schemaLocation`` se respeta su valor;
    si no, se agrega el del esquema de recepcion de DE. Devuelve el elemento
    raiz.

    Raises:
        lxml.etree.XMLSyntaxError: si el texto no es XML bien formado.
    """
    etree = _importar_opcional("lxml.etree")
    contenido = xml_de if isinstance(xml_de, bytes) else xml_de.encode("utf-8")
    raiz = etree.fromstring(contenido)
    if raiz.get(_ATRIBUTO_SCHEMA_LOCATION) is None:
        raiz.set(_ATRIBUTO_SCHEMA_LOCATION, _SCHEMA_LOCATION_RECEPCION)
    return raiz


def _build_enviar_de_request_xml(d_id: int, xml_de: str | bytes) -> bytes:
    """Arma el request ``rEnviDe`` que contiene el DE (ya firmado) en ``xDE``.

    ``rEnviDe`` declara el espacio de nombres del SIFEN como espacio por
    defecto y sus hijos son ``dId`` (con ``str(d_id)``) y ``xDE``. El ``rDE``
    se serializa aparte, con sus propias declaraciones de namespace y sus
    prefijos, y se inserta como texto (no escapado). Asi el ``DE`` conserva la
    forma canonica sobre la que se calculo la firma, use o no prefijos.
    Insertarlo como arbol no sirve: lxml quita del ``rDE`` las declaraciones
    que el padre ya tiene y reexpresa un ``rDE`` prefijado en el espacio por
    defecto, lo que invalida la firma. La salida depende solo de los
    argumentos.

    Returns:
        El request en UTF-8, con declaracion XML.

    Raises:
        lxml.etree.XMLSyntaxError: si ``xml_de`` no es XML bien formado.
    """
    etree = _importar_opcional("lxml.etree")
    documento = _with_schema_location(xml_de)
    rde = etree.tostring(documento, encoding="unicode", with_tail=False)
    return (
        f"{_APERTURA_RENVIDE}<dId>{escape(str(d_id))}</dId><xDE>{rde}</xDE></rEnviDe>"
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Lote asincrono
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DocumentoDeLote:
    """Un ``rDE`` listo para el lote y los datos que se validan en conjunto."""

    xml: str
    cdc: str
    tipo_de: str
    ruc_emisor: str


def _validar_cantidad_lote(cantidad: int) -> None:
    """Un lote lleva de 1 a :data:`MAX_LOTE` documentos (MT v150 sec. 9.2.1).

    Raises:
        ValueError: si la cantidad esta fuera de ese rango.
    """
    if cantidad > MAX_LOTE:
        raise ValueError(
            f"Un lote admite como maximo {MAX_LOTE} documentos; "
            f"se recibieron {cantidad}"
        )
    if cantidad == 0:
        raise ValueError("El lote debe incluir al menos un documento")


def _verificar_sin_blancos_entre_etiquetas(raiz: Any, posicion: int) -> None:
    """Rechaza saltos de linea, tabs o espacios entre etiquetas.

    El MT v150 sec. 7.2.4 (pp. 34-35) y la Guia de mejores practicas (p. 4) los
    prohiben. No se quitan aca: dentro del ``DE`` o de la ``Signature``
    cambiarian lo firmado. El firmador del engine ya los elimina antes de
    firmar.

    Raises:
        ValueError: si algun elemento tiene texto o cola formados solo por
            blancos entre etiquetas.
    """
    for elemento in raiz.iter():
        if not isinstance(elemento.tag, str):
            continue
        texto = elemento.text
        if len(elemento) and texto and texto.isspace():
            raise _error_blancos(posicion)
        cola = elemento.tail
        if elemento is not raiz and cola and cola.isspace():
            raise _error_blancos(posicion)


def _error_blancos(posicion: int) -> ValueError:
    return ValueError(
        f"El rDE {posicion} del lote tiene blancos entre etiquetas (MT v150 "
        "sec. 7.2.4); hay que firmarlo sin formato, porque quitarlos despues "
        "invalida la firma"
    )


def _texto_obligatorio(raiz: Any, ruta: str, campo: str, posicion: int) -> str:
    """Texto del elemento en ``ruta``; ``ValueError`` si falta o esta vacio."""
    valor = raiz.findtext(ruta)
    if not valor:
        raise ValueError(f"El rDE {posicion} del lote no tiene {campo}")
    return valor


def _documento_de_lote(xml_de: str | bytes, posicion: int) -> _DocumentoDeLote:
    """Prepara un ``rDE`` para el lote y extrae su CDC, tipo y RUC emisor.

    El ``rDE`` se serializa sin declaracion XML, con su propio ``xmlns`` (MT
    v150 sec. 7.2.2.2) y con ``xsi:schemaLocation``, como en el envio sincronico
    y en el ejemplo del MT (si es obligatorio en el lote no esta
    determinado). Los datos se leen del XML que se va a enviar, no del
    binding.

    Raises:
        ValueError: si la raiz no es un ``rDE`` del SIFEN, si falta el ``Id``
            del ``DE``, ``iTiDE`` o ``dRucEm``, o si hay blancos entre
            etiquetas.
        lxml.etree.XMLSyntaxError: si el texto no es XML bien formado.
    """
    etree = _importar_opcional("lxml.etree")
    raiz = _with_schema_location(xml_de)
    if raiz.tag != _ETIQUETA_RDE:
        raise ValueError(
            f"El documento {posicion} del lote no es un rDE del SIFEN: {raiz.tag!r}"
        )
    _verificar_sin_blancos_entre_etiquetas(raiz, posicion)
    de = raiz.find(_RUTA_DE)
    cdc = None if de is None else de.get("Id")
    if not cdc:
        raise ValueError(f"El rDE {posicion} del lote no tiene DE con Id (CDC)")
    return _DocumentoDeLote(
        xml=etree.tostring(raiz, encoding="unicode", with_tail=False),
        cdc=cdc,
        tipo_de=_texto_obligatorio(raiz, _RUTA_TIPO_DE, "iTiDE", posicion),
        ruc_emisor=_texto_obligatorio(raiz, _RUTA_RUC_EMISOR, "dRucEm", posicion),
    )


def _validar_composicion_lote(documentos: Sequence[_DocumentoDeLote]) -> None:
    """Un lote es de un solo tipo de DE y un solo RUC emisor, sin CDC repetidos.

    Fuentes: MT v150 sec. 9.2.2 (p. 47); Guia de mejores practicas (oct-2024),
    p. 6, causas a y b de 0301, y pp. 6-7, causa g de bloqueo del RUC.

    Raises:
        ValueError: si se mezclan tipos o RUC, o si un CDC se repite.
    """
    tipos = sorted({documento.tipo_de for documento in documentos})
    if len(tipos) > 1:
        raise ValueError(
            "Un lote admite un solo tipo de DE (iTiDE); se recibieron "
            + ", ".join(tipos)
        )
    rucs = sorted({documento.ruc_emisor for documento in documentos})
    if len(rucs) > 1:
        raise ValueError(
            "Un lote admite un solo RUC emisor (dRucEm); se recibieron "
            + ", ".join(rucs)
        )
    repetidos = sorted(
        cdc
        for cdc, veces in Counter(documento.cdc for documento in documentos).items()
        if veces > 1
    )
    if repetidos:
        raise ValueError(
            "Un CDC no puede repetirse en el lote: " + ", ".join(repetidos)
        )


def _build_lote_zip(documentos_xml: Sequence[str | bytes]) -> bytes:
    """Arma el ZIP que viaja en ``xDE`` de ``rEnvioLote``.

    El ZIP tiene una sola entrada XML (:data:`NOMBRE_ARCHIVO_LOTE`) con una
    unica declaracion UTF-8, la raiz ``rLoteDE`` sin namespace y los ``rDE``
    concatenados en el orden recibido, sin nada entre ellos (MT v150 sec.
    7.2.1, 7.2.2.2, 7.2.4 y 9.2.1; Guia de mejores practicas, oct-2024,
    pp. 8-9). Antes valida la cantidad, el tipo de DE, el RUC emisor y los CDC. Los
    bytes devueltos no estan en base64: el binding ``REnvioLote.xDE`` los
    codifica una sola vez al serializar. La salida depende solo de la entrada.

    Raises:
        ValueError: si el lote no cumple alguna de esas reglas.
        lxml.etree.XMLSyntaxError: si un documento no es XML bien formado.
    """
    _validar_cantidad_lote(len(documentos_xml))
    documentos = [
        _documento_de_lote(xml_de, posicion)
        for posicion, xml_de in enumerate(documentos_xml, start=1)
    ]
    _validar_composicion_lote(documentos)
    contenido = (
        _DECLARACION_LOTE
        + _APERTURA_LOTE
        + "".join(documento.xml for documento in documentos)
        + _CIERRE_LOTE
    ).encode("utf-8")

    entrada = zipfile.ZipInfo(NOMBRE_ARCHIVO_LOTE, date_time=_FECHA_ENTRADA_ZIP)
    entrada.compress_type = zipfile.ZIP_DEFLATED
    archivo = io.BytesIO()
    with zipfile.ZipFile(archivo, "w") as zip_lote:
        zip_lote.writestr(entrada, contenido)
    return archivo.getvalue()


def _verificar_tamano_mensaje_lote(envio: REnvioLote) -> None:
    """Rechaza un ``rEnvioLote`` cuyo sobre SOAP supere 1000 KB.

    Se mide el request serializado dentro del sobre SOAP 1.2, con el ZIP ya
    en base64 (ver :data:`MAX_BYTES_MENSAJE_LOTE`).

    Raises:
        ValueError: si el mensaje supera :data:`MAX_BYTES_MENSAJE_LOTE`.
    """
    tamano = len(_wrap_soap_envelope(_serializador().render(envio)))
    if tamano > MAX_BYTES_MENSAJE_LOTE:
        raise ValueError(
            f"El mensaje del lote ocupa {tamano} bytes y el SIFEN admite hasta "
            f"{MAX_BYTES_MENSAJE_LOTE} (1000 KB); dividir el lote"
        )


class TransmisionDE(TransmisionBase):
    """Envia DE al servicio sincrono de recepcion y lotes al asincrono.

    Ambos envios tienen efecto fiscal: el transporte solo los repite ante un
    :class:`~kilasifen.engine.sdk.errors.SifenRequestNotSentError`.
    """

    def _xml_para_envio(self, rde: Any, sign: bool) -> str:
        """Serializa ``rde`` y, si corresponde, lo firma con el ``Id`` del DE.

        El namespace del SIFEN queda como espacio por defecto, sin prefijos.
        Sin ``Id`` (binding sin atributo ``DE`` o ``Id`` vacio) el documento
        se envia sin firmar.
        """
        xml = self._serialize(rde, ns_map=_NS_MAP_RDE)
        if not sign:
            return xml
        de = getattr(rde, "DE", _SIN_DE)
        doc_id = None if de is _SIN_DE else de.Id
        if doc_id:
            xml = self._sign_xml(xml, doc_id)
        return xml

    def enviar_de(self, rde: Any, sign: bool = True) -> RRetEnviDe:
        """Serializa, firma (si ``sign``) y envia un DE al SIFEN.

        Solo vuelve a enviar (hasta ``max_retries`` veces, ``0`` por defecto)
        si la solicitud no llego al SIFEN; ante un resultado incierto lanza el
        error en el primer intento.
        """
        xml = self._xml_para_envio(rde, sign)
        solicitud = _build_enviar_de_request_xml(d_id=_generate_id(), xml_de=xml)
        respuesta = self._send_raw_xml("recep_de", solicitud)
        return self._como_respuesta(respuesta, RRetEnviDe)

    def enviar_de_xml(self, xml_de: str | bytes) -> RRetEnviDe:
        """Envia un ``rDE`` que ya viene firmado, sin serializar ni firmar.

        Raises:
            UnicodeDecodeError: si ``xml_de`` son bytes que no son UTF-8.
            lxml.etree.XMLSyntaxError: si el XML esta mal formado; en ese caso
                no se envia nada.
            SifenUnexpectedResponseError: si la respuesta es un SOAP Fault,
                el sobre de otra operacion o un cuerpo ilegible (resultado
                incierto).
        """
        if isinstance(xml_de, bytes):
            xml_de = xml_de.decode("utf-8")
        solicitud = _build_enviar_de_request_xml(d_id=_generate_id(), xml_de=xml_de)
        respuesta = self._send_raw_xml("recep_de", solicitud)
        return self._como_respuesta(respuesta, RRetEnviDe)

    def enviar_lote(
        self,
        lista_rde: Sequence[Any],
        lote_id: int | None = None,
        sign: bool = True,
    ) -> RResEnviLoteDe:
        """Envia hasta :data:`MAX_LOTE` DE en un lote asincrono.

        Cada documento se serializa y, si corresponde, se firma, en el orden
        recibido; despues sigue el camino de :meth:`enviar_lote_xml`. Sin
        ``lote_id`` (o con ``0``) se genera uno.

        Raises:
            ValueError: si la lista esta vacia o supera :data:`MAX_LOTE`
                (antes de serializar), o si el lote no cumple las reglas de
                :meth:`enviar_lote_xml`.
        """
        _validar_cantidad_lote(len(lista_rde))
        documentos = [self._xml_para_envio(rde, sign) for rde in lista_rde]
        return self._enviar_lote(documentos, lote_id)

    def enviar_lote_xml(
        self,
        lista_xml: Sequence[str | bytes],
        lote_id: int | None = None,
    ) -> RResEnviLoteDe:
        """Envia en un lote asincrono ``rDE`` que ya vienen firmados.

        Los documentos no se firman ni se modifican, salvo que se les agrega
        ``xsi:schemaLocation`` si no lo tienen. Antes de enviar se valida que
        sean de 1 a :data:`MAX_LOTE`, del mismo tipo de DE (``iTiDE``) y del
        mismo RUC emisor (``dRucEm``), sin CDC repetidos, sin blancos entre
        etiquetas y con un mensaje de hasta :data:`MAX_BYTES_MENSAJE_LOTE`
        bytes. El ZIP armado (ver :func:`_build_lote_zip`) viaja en ``xDE``
        codificado en base64 una sola vez. Sin ``lote_id`` (o con ``0``) se
        genera uno.

        Una respuesta ``0300`` trae el numero de lote (``dProtConsLote``) para
        consultarlo; con ``0301`` el lote no se procesa.

        Raises:
            ValueError: si el lote no cumple alguna regla; en ese caso no se
                envia nada.
            lxml.etree.XMLSyntaxError: si un documento no es XML bien formado.
        """
        return self._enviar_lote(lista_xml, lote_id)

    def _enviar_lote(
        self,
        documentos: Sequence[str | bytes],
        lote_id: int | None,
    ) -> RResEnviLoteDe:
        envio = REnvioLote(
            dId=lote_id if lote_id else _generate_id(),
            # Los bytes del ZIP, no su base64: el binding (``xDE`` con formato
            # base64, XSD WS_SiRecepLoteDE_v141.xsd) ya los codifica.
            xDE=_build_lote_zip(documentos),
        )
        _verificar_tamano_mensaje_lote(envio)
        respuesta = self._get_client("recep_lote").send(envio)
        return self._como_respuesta(respuesta, RResEnviLoteDe)
