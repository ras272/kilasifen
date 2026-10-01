"""Envio de Documentos Electronicos (DE) al SIFEN, uno a uno o por lote."""

from __future__ import annotations

import base64
from typing import Any

from kilasifen.engine.de.bindings.v150.ws_si_recep_de_v150 import RRetEnviDe
from kilasifen.engine.de.bindings.v150.ws_si_recep_lote_de_v141 import (
    REnvioLote,
    RResEnviLoteDe,
)
from kilasifen.engine.transmision.base import (
    TransmisionBase,
    _generate_id,
    _importar_opcional,
)

__all__ = ["MAX_LOTE", "TransmisionDE"]

#: Cantidad maxima de documentos que admite un lote.
MAX_LOTE: int = 50

_NS_SIFEN = "http://ekuatia.set.gov.py/sifen/xsd"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_ATRIBUTO_SCHEMA_LOCATION = f"{{{_NS_XSI}}}schemaLocation"
_SCHEMA_LOCATION_RECEPCION = f"{_NS_SIFEN} siRecepDE_v150.xsd"

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
    se inserta como arbol (no como texto escapado), de modo que una firma
    calculada sobre un ``rDE`` sin prefijos sigue verificando. La salida
    depende solo de los argumentos.

    Returns:
        El request en UTF-8, con declaracion XML.

    Raises:
        lxml.etree.XMLSyntaxError: si ``xml_de`` no es XML bien formado.
    """
    etree = _importar_opcional("lxml.etree")
    documento = _with_schema_location(xml_de)

    solicitud = etree.Element(f"{{{_NS_SIFEN}}}rEnviDe", nsmap={None: _NS_SIFEN})
    identificador = etree.SubElement(solicitud, f"{{{_NS_SIFEN}}}dId")
    identificador.text = str(d_id)
    contenedor = etree.SubElement(solicitud, f"{{{_NS_SIFEN}}}xDE")
    contenedor.append(documento)

    return etree.tostring(solicitud, encoding="UTF-8", xml_declaration=True)


class TransmisionDE(TransmisionBase):
    """Envia DE al servicio sincrono de recepcion y lotes al asincrono.

    Ambos envios tienen efecto fiscal: el transporte solo los repite ante un
    :class:`~kilasifen.engine.sdk.errors.SifenRequestNotSentError`.
    """

    def _xml_para_envio(self, rde: Any, sign: bool) -> str:
        """Serializa ``rde`` y, si corresponde, lo firma con el ``Id`` del DE.

        Sin ``Id`` (binding sin atributo ``DE`` o ``Id`` vacio) el documento
        se envia sin firmar.
        """
        xml = self._serialize(rde)
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
        """
        if isinstance(xml_de, bytes):
            xml_de = xml_de.decode("utf-8")
        solicitud = _build_enviar_de_request_xml(d_id=_generate_id(), xml_de=xml_de)
        respuesta = self._send_raw_xml("recep_de", solicitud)
        return self._como_respuesta(respuesta, RRetEnviDe)

    def enviar_lote(
        self,
        lista_rde: list,
        lote_id: int | None = None,
        sign: bool = True,
    ) -> RResEnviLoteDe:
        """Envia hasta :data:`MAX_LOTE` DE en un lote asincrono.

        Cada documento se serializa y, si corresponde, se firma, en el orden
        recibido. Los textos se unen con saltos de linea y viajan codificados
        en base64 en ``xDE``. Sin ``lote_id`` (o con ``0``) se genera uno.

        Raises:
            ValueError: si la lista esta vacia o supera :data:`MAX_LOTE`.
        """
        cantidad = len(lista_rde)
        if cantidad > MAX_LOTE:
            raise ValueError(
                f"Un lote admite como maximo {MAX_LOTE} documentos; "
                f"se recibieron {cantidad}"
            )
        if cantidad == 0:
            raise ValueError("El lote debe incluir al menos un documento")

        documentos = [self._xml_para_envio(rde, sign) for rde in lista_rde]
        contenido = base64.b64encode("\n".join(documentos).encode("utf-8"))

        envio = REnvioLote(
            dId=lote_id if lote_id else _generate_id(),
            xDE=contenido,
        )
        respuesta = self._get_client("recep_lote").send(envio)
        return self._como_respuesta(respuesta, RResEnviLoteDe)
