"""Firmador XMLDSig con certificado PKCS12 para documentos y eventos del SIFEN.

El modulo hace tres cosas:

* decodifica una sola vez el contenedor PKCS12 (``.pfx``/``.p12``) del emisor
  y conserva en memoria la clave privada y el certificado;
* firma XML con una firma *enveloped* RSA-SHA256, canonicalizacion exclusiva
  y digest SHA-256, con la forma exacta que acepta la SET (namespace XMLDSig
  por defecto, sin prefijo ``ds:``);
* mantiene una cache LRU de firmadores por proceso, porque decodificar un
  PKCS12 (derivar la clave y descifrar) es costoso.

``lxml`` y ``cryptography`` pertenecen al extra opcional de firma y solo se
importan dentro de las funciones que los usan: importar este modulo funciona
sin el extra instalado.
"""

from __future__ import annotations

import base64
import hashlib
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from kilasifen.engine.sdk.errors import SifenSignatureError

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
    from lxml import etree

__all__ = ["Pkcs12Signer", "clear_pkcs12_signer_cache", "get_pkcs12_signer"]

_NS_DS = "http://www.w3.org/2000/09/xmldsig#"
_ALG_C14N_EXC = "http://www.w3.org/2001/10/xml-exc-c14n#"
_ALG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_ALG_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
_ALG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

_ETIQUETA_FIRMA = f"{{{_NS_DS}}}Signature"

_MENSAJE_CARGA = "No se pudo cargar el certificado PKCS12"
_MENSAJE_FIRMA = "No se pudo firmar el XML"

#: Cantidad maxima de firmadores conservados en la cache del proceso.
_TAMANO_CACHE = 8

#: Ancho de linea del cuerpo PEM del certificado dentro de ``X509Certificate``.
_ANCHO_PEM = 64

#: Nombre base de la instruccion de procesamiento que marca, durante la
#: serializacion, el lugar donde va la ``Signature``.
_MARCADOR = "kilasifen-firma"
_INTENTOS_MARCADOR = 16

_cache: OrderedDict[tuple[Any, Any], Pkcs12Signer] = OrderedDict()
_candado_cache = threading.Lock()


class Pkcs12Signer:
    """Firmador reutilizable construido a partir de un PKCS12.

    El PKCS12 se decodifica una sola vez, en el constructor. Despues el objeto
    no cambia: :meth:`sign` puede llamarse desde varios hilos a la vez sobre
    la misma instancia.
    """

    __slots__ = ("_certificado_b64", "_clave")

    def __init__(
        self,
        pkcs12_data: bytes,
        pkcs12_password: str | bytes | None,
    ) -> None:
        try:
            self._clave, self._certificado_b64 = _cargar_pkcs12(
                _normalizar_datos(pkcs12_data),
                _normalizar_password(pkcs12_password),
            )
        except SifenSignatureError:
            raise
        except Exception as exc:
            raise SifenSignatureError(_MENSAJE_CARGA) from exc

    def sign(
        self,
        xml_input: str | bytes | etree._Element,
        doc_id: str | None,
    ) -> str:
        """Firma ``xml_input`` y devuelve el documento firmado como texto.

        Args:
            xml_input: documento como ``str``, ``bytes`` o elemento ``lxml``.
                Nunca se modifica: se trabaja sobre una copia.
            doc_id: valor del atributo ``Id`` del nodo a firmar. La
                ``Signature`` queda como hermana inmediatamente posterior de
                ese nodo, o como ultimo hijo de la raiz si el nodo es la
                raiz. Con ``None`` o ``""`` se firma el documento completo.

        Returns:
            El elemento raiz serializado, sin declaracion XML.

        Raises:
            SifenSignatureError: si el documento no se puede firmar.
        """
        try:
            return self._firmar(xml_input, doc_id)
        except SifenSignatureError:
            raise
        except Exception as exc:
            raise SifenSignatureError(_MENSAJE_FIRMA) from exc

    def _firmar(self, xml_input: Any, doc_id: str | None) -> str:
        raiz = _parsear(xml_input)
        if raiz.tag == _ETIQUETA_FIRMA:
            raise ValueError("la raiz del documento no puede ser una Signature")
        _quitar_firmas_previas(raiz)
        _normalizar_blancos(raiz)
        nodo, uri = _resolver_nodo(raiz, doc_id)
        firma = self._armar_firma(uri, _digest_b64(nodo))
        return _serializar_con_firma(raiz, nodo, firma)

    def _armar_firma(self, uri: str, digest: str) -> str:
        """Construye la ``Signature`` aislada y la devuelve serializada."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from lxml import etree

        def hijo(padre: etree._Element, nombre: str, **atributos: str):
            return etree.SubElement(padre, f"{{{_NS_DS}}}{nombre}", atributos)

        firma = etree.Element(_ETIQUETA_FIRMA, nsmap={None: _NS_DS})
        info = hijo(firma, "SignedInfo")
        hijo(info, "CanonicalizationMethod", Algorithm=_ALG_C14N_EXC)
        hijo(info, "SignatureMethod", Algorithm=_ALG_RSA_SHA256)
        referencia = hijo(info, "Reference", URI=uri)
        transformaciones = hijo(referencia, "Transforms")
        hijo(transformaciones, "Transform", Algorithm=_ALG_ENVELOPED)
        hijo(transformaciones, "Transform", Algorithm=_ALG_C14N_EXC)
        hijo(referencia, "DigestMethod", Algorithm=_ALG_SHA256)
        hijo(referencia, "DigestValue").text = digest

        valor_firma = self._clave.sign(
            _c14n_exclusiva(info),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        hijo(firma, "SignatureValue").text = _b64(valor_firma)
        datos_x509 = hijo(hijo(firma, "KeyInfo"), "X509Data")
        hijo(datos_x509, "X509Certificate").text = self._certificado_b64
        return etree.tostring(firma, encoding="unicode")


def get_pkcs12_signer(
    pkcs12_data: bytes,
    pkcs12_password: str | bytes | None,
) -> Pkcs12Signer:
    """Devuelve un firmador para el par (PKCS12, contrasena), usando la cache.

    La cache compara por contenido: los mismos bytes con la misma contrasena
    (``"x"`` equivale a ``b"x"``) devuelven siempre el mismo objeto. Guarda
    hasta ocho firmadores y descarta el usado hace mas tiempo. Un fallo al
    construir el firmador no se guarda: la proxima llamada vuelve a intentar.

    Raises:
        SifenSignatureError: si el PKCS12 o la contrasena no son validos.
    """
    try:
        datos = _normalizar_datos(pkcs12_data)
        password = _normalizar_password(pkcs12_password)
        clave = (datos, password)
        hash(clave)
    except Exception as exc:
        raise SifenSignatureError(_MENSAJE_CARGA) from exc

    with _candado_cache:
        firmador = _cache.get(clave)
        if firmador is not None:
            _cache.move_to_end(clave)
            return firmador

    # La decodificacion ocurre fuera del candado para no bloquear a los
    # hilos que piden otros certificados.
    nuevo = Pkcs12Signer(datos, password)

    with _candado_cache:
        firmador = _cache.get(clave)
        if firmador is None:
            firmador = _cache[clave] = nuevo
            while len(_cache) > _TAMANO_CACHE:
                _cache.popitem(last=False)
        else:
            _cache.move_to_end(clave)
        return firmador


def clear_pkcs12_signer_cache() -> None:
    """Vacia la cache de firmadores; los ya entregados siguen funcionando."""
    with _candado_cache:
        _cache.clear()


def _normalizar_datos(pkcs12_data: Any) -> Any:
    """Convierte ``bytearray``/``memoryview`` en ``bytes``; el resto, tal cual."""
    if isinstance(pkcs12_data, (bytearray, memoryview)):
        return bytes(pkcs12_data)
    return pkcs12_data


def _normalizar_password(pkcs12_password: Any) -> Any:
    """Lleva la contrasena a ``bytes`` (``str`` se codifica en UTF-8).

    ``None`` se conserva (PKCS12 sin cifrar). Otros tipos pasan sin cambios y
    los rechaza el decodificador.
    """
    if isinstance(pkcs12_password, str):
        return pkcs12_password.encode("utf-8")
    if isinstance(pkcs12_password, (bytearray, memoryview)):
        return bytes(pkcs12_password)
    return pkcs12_password


def _cargar_pkcs12(datos: Any, password: Any) -> tuple[RSAPrivateKey, str]:
    """Decodifica el PKCS12: devuelve la clave RSA y el cuerpo PEM del certificado.

    El cargador se busca en el modulo ``pkcs12`` en el momento de la llamada
    (los tests lo reemplazan para contar decodificaciones o inyectar fallos).
    Los certificados adicionales del contenedor se ignoran.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

    clave, certificado, _adicionales = pkcs12.load_key_and_certificates(datos, password)
    if clave is None:
        raise ValueError("el PKCS12 no contiene clave privada")
    if certificado is None:
        raise ValueError("el PKCS12 no contiene certificado")
    if not isinstance(clave, rsa.RSAPrivateKey):
        raise TypeError("la clave privada del PKCS12 no es RSA")
    return clave, _cuerpo_pem(certificado.public_bytes(Encoding.DER))


def _cuerpo_pem(der: bytes) -> str:
    """Base64 del DER en lineas de 64 caracteres, cada una terminada en ``\\n``."""
    texto = _b64(der)
    return "".join(
        texto[inicio : inicio + _ANCHO_PEM] + "\n"
        for inicio in range(0, len(texto), _ANCHO_PEM)
    )


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def _parsear(xml_input: Any) -> etree._Element:
    """Parsea la entrada en un arbol nuevo, propio de esta firma.

    ``str`` se codifica en UTF-8; ``bytes`` respeta su declaracion de
    codificacion; un elemento ``lxml`` se serializa y se vuelve a parsear, de
    modo que el arbol del llamador nunca se modifica. El parser no resuelve
    entidades, no accede a la red ni carga DTD, y se rechaza cualquier
    documento con ``DOCTYPE``.
    """
    from lxml import etree

    if isinstance(xml_input, str):
        datos = xml_input.encode("utf-8")
    elif isinstance(xml_input, (bytes, bytearray, memoryview)):
        datos = bytes(xml_input)
    elif isinstance(xml_input, etree._ElementTree):
        return _parsear(xml_input.getroot())
    elif isinstance(xml_input, etree._Element) and isinstance(xml_input.tag, str):
        datos = etree.tostring(xml_input, encoding="UTF-8", with_tail=False)
    else:
        raise TypeError(f"tipo de documento no soportado: {type(xml_input).__name__}")

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False,
        huge_tree=False,
        remove_blank_text=False,
        remove_comments=False,
        remove_pis=False,
        strip_cdata=True,
        collect_ids=False,
    )
    raiz = etree.fromstring(datos, parser=parser)
    info = raiz.getroottree().docinfo
    if info.doctype or info.internalDTD is not None or info.externalDTD is not None:
        raise ValueError("no se admiten documentos con DOCTYPE")
    return raiz


def _quitar_firmas_previas(raiz: etree._Element) -> None:
    """Elimina toda ``Signature`` XMLDSig descendiente, con su texto de cola."""
    for firma in list(raiz.iterdescendants(_ETIQUETA_FIRMA)):
        padre = firma.getparent()
        if padre is not None:
            padre.remove(firma)


def _normalizar_blancos(raiz: etree._Element) -> None:
    """Quita el texto y la cola de los elementos cuando son solo blancos.

    Solo se recorren elementos: las colas de comentarios e instrucciones de
    procesamiento se conservan. ``xml:space`` no se tiene en cuenta.
    """
    from lxml import etree

    for elemento in raiz.iter(etree.Element):
        texto = elemento.text
        if texto is not None and (not texto or texto.isspace()):
            elemento.text = None
        cola = elemento.tail
        if cola is not None and (not cola or cola.isspace()):
            elemento.tail = None


def _resolver_nodo(
    raiz: etree._Element, doc_id: str | None
) -> tuple[etree._Element, str]:
    """Devuelve el nodo a firmar y la URI de la ``Reference``.

    Con ``doc_id`` se busca el unico elemento cuyo atributo ``Id`` vale
    ``doc_id``. Para que un verificador estandar resuelva la misma
    referencia, la unicidad se comprueba contra todo atributo de nombre local
    ``Id`` (con o sin namespace) y se exige que el encontrado sea el ``Id``
    sin namespace. Sin ``doc_id`` se firma la raiz.
    """
    if doc_id is None or doc_id == "":
        valor = raiz.get("Id")
        if valor is None:
            valor = raiz.get("ID")
        return raiz, "" if valor is None else f"#{valor}"

    if not isinstance(doc_id, str):
        raise TypeError("doc_id debe ser str o None")
    if doc_id.startswith("#"):
        raise ValueError("doc_id no debe empezar con '#'")

    encontrados = raiz.xpath("//*[@*[local-name() = 'Id'] = $valor]", valor=doc_id)
    if not encontrados:
        raise ValueError("ningun elemento tiene el Id indicado")
    if len(encontrados) > 1:
        raise ValueError("mas de un elemento tiene el Id indicado")
    nodo = encontrados[0]
    if nodo.get("Id") != doc_id:
        raise ValueError("el Id indicado no esta en un atributo Id sin namespace")
    return nodo, f"#{doc_id}"


def _c14n_exclusiva(nodo: etree._Element) -> bytes:
    """Canonicalizacion exclusiva 1.0 sin comentarios del subarbol de ``nodo``."""
    from lxml import etree

    return etree.tostring(nodo, method="c14n", exclusive=True, with_comments=False)


def _digest_b64(nodo: etree._Element) -> str:
    return _b64(hashlib.sha256(_c14n_exclusiva(nodo)).digest())


def _serializar_con_firma(
    raiz: etree._Element,
    nodo: etree._Element,
    firma: str,
) -> str:
    """Serializa la raiz con la ``Signature`` ya serializada en su lugar.

    La firma se pone donde quedo una instruccion de procesamiento temporal:
    detras de ``nodo``, o al final de la raiz si ``nodo`` es la raiz. Asi
    conserva su propia declaracion de namespace por defecto aunque un
    ancestro declare un prefijo para XMLDSig (``lxml`` reasignaria ese
    prefijo al mover un elemento ya construido), y el resto del documento se
    serializa sin cambios.
    """
    from lxml import etree

    for intento in range(_INTENTOS_MARCADOR):
        nombre = _MARCADOR if intento == 0 else f"{_MARCADOR}-{intento}"
        marcador = etree.ProcessingInstruction(nombre)
        if nodo.getparent() is None:
            raiz.append(marcador)
        else:
            nodo.addnext(marcador)
        texto_marcador = etree.tostring(marcador, encoding="unicode", with_tail=False)
        texto = etree.tostring(raiz, encoding="unicode", with_tail=False)
        if texto.count(texto_marcador) == 1:
            return texto.replace(texto_marcador, firma)
        # El documento ya trae ese texto (en un comentario o una instruccion
        # de procesamiento): se prueba con otro nombre.
        padre = marcador.getparent()
        if padre is not None:
            padre.remove(marcador)
    raise RuntimeError("no se pudo ubicar la Signature en el documento")
