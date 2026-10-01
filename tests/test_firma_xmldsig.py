"""Tests del firmador XMLDSig PKCS12 (``kilasifen.engine.sdk.signer``).

Cubren el perfil exacto de la firma que acepta la SET, la ubicacion de la
``Signature``, el tratamiento de firmas previas, la normalizacion de blancos,
los tipos de entrada, los errores, la cache de firmadores y la compatibilidad
con los goldens de ``tests/golden``.
"""

from __future__ import annotations

import base64
import codecs
import hashlib
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

etree = pytest.importorskip("lxml.etree")
signxml = pytest.importorskip("signxml")
pytest.importorskip("cryptography")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from kilasifen.engine import firma  # noqa: E402
from kilasifen.engine.de.bindings.v150.fe_v141 import RDe  # noqa: E402
from kilasifen.engine.sdk.errors import SifenSignatureError  # noqa: E402
from kilasifen.engine.sdk.signer import (  # noqa: E402
    clear_pkcs12_signer_cache,
    get_pkcs12_signer,
)

pytestmark = pytest.mark.filterwarnings("ignore::xsdata.exceptions.ConverterWarning")

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_SIFEN = "http://ekuatia.set.gov.py/sifen/xsd"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
ALG_C14N_EXC = "http://www.w3.org/2001/10/xml-exc-c14n#"
ALG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ALG_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
ALG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

PASSWORD = "test1234"
MENSAJE_CARGA = "No se pudo cargar el certificado PKCS12"
MENSAJE_FIRMA = "No se pudo firmar el XML"
APERTURA_FIRMA = f'<Signature xmlns="{NS_DS}">'
FIRMA_DS = f"{{{NS_DS}}}Signature"
CARGADOR = (
    "cryptography.hazmat.primitives.serialization.pkcs12.load_key_and_certificates"
)

DIR_TESTS = Path(__file__).resolve().parent
RAIZ_REPO = DIR_TESTS.parent
RUTA_PFX = DIR_TESTS / "test_cert.pfx"
RUTA_MUESTRA = (
    RAIZ_REPO
    / "kilasifen"
    / "engine"
    / "de"
    / "samples"
    / "v150"
    / "factura_electronica.xml"
)
GOLDENS = sorted((DIR_TESTS / "golden").glob("*.xml"))

#: CDC ficticio de 44 digitos (solo importa el formato): tipo, RUC, DV,
#: establecimiento, punto, numero, tipo de contribuyente, fecha, tipo de
#: emision, codigo de seguridad y digito verificador.
CDC_FICTICIO = "".join(
    ("01", "00000000", "0", "001", "001", "0000001", "1", "20260101", "1")
    + ("000000001", "0")
)
assert len(CDC_FICTICIO) == 44


# ---------------------------------------------------------------------------
# Material criptografico
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Material:
    """Certificado del firmante en las formas que usan los verificadores."""

    cert_pem: bytes
    clave_publica: rsa.RSAPublicKey
    cuerpo_pem: str


@dataclass(frozen=True)
class Especiales:
    """PKCS12 generados en memoria para casos particulares."""

    sin_cifrar: bytes
    sin_cifrar_material: Material
    con_ca: bytes
    con_ca_material: Material
    ca_cuerpo_pem: str
    con_password_unicode: bytes
    clave_ec: bytes
    solo_certificado: bytes
    solo_clave: bytes
    clave_rsa: rsa.RSAPrivateKey
    certificado: x509.Certificate


def _material(certificado: x509.Certificate) -> Material:
    pem = certificado.public_bytes(serialization.Encoding.PEM)
    lineas = pem.decode("ascii").splitlines()
    cuerpo = "".join(linea + "\n" for linea in lineas[1:-1])
    return Material(
        cert_pem=pem,
        clave_publica=certificado.public_key(),
        cuerpo_pem=cuerpo,
    )


def _certificado(clave, nombre: str, emisor=None, clave_emisor=None):
    sujeto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre)])
    return (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(emisor if emisor is not None else sujeto)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2025, 1, 1, tzinfo=timezone.utc))
        .not_valid_after(datetime(2035, 1, 1, tzinfo=timezone.utc))
        .sign(clave_emisor if clave_emisor is not None else clave, hashes.SHA256())
    )


def _serializar_pkcs12(clave, certificado, cas=None, password: bytes | None = None):
    cifrado = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"kilasifen-prueba",
        key=clave,
        cert=certificado,
        cas=cas,
        encryption_algorithm=cifrado,
    )


@pytest.fixture(scope="module")
def pfx_prueba() -> bytes:
    if not RUTA_PFX.exists():
        pytest.skip("tests/test_cert.pfx no existe")
    return RUTA_PFX.read_bytes()


@pytest.fixture(scope="module")
def material_prueba(pfx_prueba: bytes) -> Material:
    # Se decodifica una sola vez, antes de que cualquier test instale un
    # contador sobre el cargador de PKCS12.
    _clave, certificado, _cas = pkcs12.load_key_and_certificates(
        pfx_prueba, PASSWORD.encode("utf-8")
    )
    return _material(certificado)


@pytest.fixture(scope="module")
def especiales() -> Especiales:
    clave = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    certificado = _certificado(clave, "Firmante de prueba")
    clave_ca = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    nombre_ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA de prueba")])
    certificado_ca = _certificado(clave_ca, "CA de prueba")
    certificado_hijo = _certificado(
        clave, "Firmante con CA", emisor=nombre_ca, clave_emisor=clave_ca
    )
    clave_ec = ec.generate_private_key(ec.SECP256R1())
    return Especiales(
        sin_cifrar=_serializar_pkcs12(clave, certificado),
        sin_cifrar_material=_material(certificado),
        con_ca=_serializar_pkcs12(
            clave, certificado_hijo, cas=[certificado_ca], password=b"test1234"
        ),
        con_ca_material=_material(certificado_hijo),
        ca_cuerpo_pem=_material(certificado_ca).cuerpo_pem,
        con_password_unicode=_serializar_pkcs12(
            clave, certificado, password="contraseña".encode("utf-8")
        ),
        clave_ec=_serializar_pkcs12(
            clave_ec, _certificado(clave_ec, "Firmante EC"), password=b"test1234"
        ),
        solo_certificado=_serializar_pkcs12(None, certificado),
        solo_clave=_serializar_pkcs12(clave, None),
        clave_rsa=clave,
        certificado=certificado,
    )


def _generar_pkcs12_distintos(especiales: Especiales, cantidad: int) -> list[bytes]:
    """Cada serializacion cifrada usa una sal aleatoria: bytes distintos."""
    contenedores = [
        _serializar_pkcs12(
            especiales.clave_rsa, especiales.certificado, password=b"test1234"
        )
        for _ in range(cantidad)
    ]
    assert len(set(contenedores)) == cantidad
    return contenedores


@pytest.fixture(autouse=True)
def _cache_limpia():
    clear_pkcs12_signer_cache()
    yield
    clear_pkcs12_signer_cache()


@pytest.fixture
def firmador(pfx_prueba: bytes):
    return get_pkcs12_signer(pfx_prueba, PASSWORD)


def _contar_cargas(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Envuelve el cargador de PKCS12 con un contador de invocaciones."""
    llamadas: list[int] = []
    original = pkcs12.load_key_and_certificates

    def envoltorio(*args, **kwargs):
        llamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(CARGADOR, envoltorio)
    return llamadas


# ---------------------------------------------------------------------------
# Documentos de prueba
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rde_muestra() -> RDe:
    return RDe.from_path(RUTA_MUESTRA)


def _doc_sifen(cdc: str = CDC_FICTICIO, contenido_de: str | None = None) -> str:
    """``rDE`` minimo y compacto, con namespace SIFEN por defecto."""
    if contenido_de is None:
        contenido_de = (
            "<dDVId>0</dDVId><gTimb><dDesTiDE>Factura electrónica</dDesTiDE></gTimb>"
        )
    return (
        f'<rDE xmlns="{NS_SIFEN}" xmlns:xsi="{NS_XSI}">'
        "<dVerFor>150</dVerFor>"
        f'<DE Id="{cdc}">{contenido_de}</DE>'
        "<gCamFuFD><dCarQR>https://qr.invalid/consulta?nVersion=150&amp;Id=1"
        "</dCarQR></gCamFuFD>"
        "</rDE>"
    )


def _indentar(xml: str) -> str:
    raiz = etree.fromstring(xml.encode("utf-8"))
    etree.indent(raiz, space="  ")
    return etree.tostring(raiz, encoding="unicode")


def _doc_evento(event_id: str = "123") -> str:
    """``gGroupGesEve`` serializado con ``ElementTree`` como el builder de eventos.

    El namespace SIFEN por defecto se declara como atributo ``xmlns`` de la
    raiz (mismo texto de salida) para no registrar prefijos globales con
    ``ElementTree.register_namespace``.
    """
    raiz = ET.Element("gGroupGesEve", {"xmlns": NS_SIFEN})
    r_ges_eve = ET.SubElement(raiz, "rGesEve")
    r_eve = ET.SubElement(r_ges_eve, "rEve", {"Id": event_id})
    ET.SubElement(r_eve, "dFecFirma").text = "2026-01-01T10:00:00"
    ET.SubElement(r_eve, "dVerFor").text = "150"
    grupo = ET.SubElement(r_eve, "gGroupTiEvt")
    cancelacion = ET.SubElement(grupo, "rGeVeCan")
    ET.SubElement(cancelacion, "Id").text = CDC_FICTICIO
    ET.SubElement(cancelacion, "mOtEve").text = "Error de carga"
    return ET.tostring(raiz, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# Verificadores independientes
# ---------------------------------------------------------------------------


def _arbol(salida: str):
    return etree.fromstring(salida.encode("utf-8"))


def _verificar_xmldsig(salida: str, material: Material, id_attribute="Id"):
    """Verifica con ``signxml`` y devuelve el nodo firmado."""
    resultado = signxml.XMLVerifier().verify(
        salida.encode("utf-8"),
        x509_cert=material.cert_pem,
        id_attribute=id_attribute,
    )
    return resultado.signed_xml


def _verificar_rsa(salida: str, material: Material) -> None:
    """Verifica ``SignatureValue`` sobre la c14n exclusiva de ``SignedInfo``."""
    raiz = _arbol(salida)
    info = raiz.find(f".//{{{NS_DS}}}SignedInfo")
    valor = raiz.find(f".//{{{NS_DS}}}SignatureValue").text
    canonico = etree.tostring(info, method="c14n", exclusive=True, with_comments=False)
    material.clave_publica.verify(
        base64.b64decode(valor), canonico, padding.PKCS1v15(), hashes.SHA256()
    )


def _digest_esperado(nodo) -> str:
    canonico = etree.tostring(nodo, method="c14n", exclusive=True, with_comments=False)
    return base64.b64encode(hashlib.sha256(canonico).digest()).decode("ascii")


def _hijos(elemento) -> list[str]:
    """Nombres locales de los hijos elemento (sin comentarios ni PI)."""
    return [
        etree.QName(hijo).localname for hijo in elemento if isinstance(hijo.tag, str)
    ]


def _etiquetas(elemento) -> list[str]:
    """Etiquetas completas (``{ns}nombre``) de los hijos elemento."""
    return [hijo.tag for hijo in elemento if isinstance(hijo.tag, str)]


def _firmas(salida: str) -> list:
    return _arbol(salida).findall(f".//{{{NS_DS}}}Signature")


def _digest_de_salida(salida: str) -> str:
    return _arbol(salida).find(f".//{{{NS_DS}}}DigestValue").text


def _uri(salida: str) -> str:
    return _arbol(salida).find(f".//{{{NS_DS}}}Reference").get("URI")


def _subcadena(texto: str, inicio: str, fin: str) -> str:
    desde = texto.index(inicio)
    hasta = texto.index(fin, desde) + len(fin)
    return texto[desde:hasta]


def _sin_signature(texto: str) -> str:
    firma_texto = _subcadena(texto, "<Signature ", "</Signature>")
    return texto.replace(firma_texto, "", 1)


# ---------------------------------------------------------------------------
# A. Perfil XMLDSig
# ---------------------------------------------------------------------------


def test_firma_unica_con_namespace_xmldsig_por_defecto(pfx_prueba, rde_muestra):
    entrada = rde_muestra.to_xml()
    salida = firma.sign_xml(entrada, pfx_prueba, PASSWORD, rde_muestra.DE.Id)

    assert len(_firmas(salida)) == 1
    assert salida.count(APERTURA_FIRMA) == 1
    assert "ds:" not in salida
    assert ":Signature" not in salida


def test_signature_tiene_forma_exacta(firmador):
    salida = firmador.sign(_doc_sifen(), CDC_FICTICIO)

    literal = re.escape
    patron = (
        literal(APERTURA_FIRMA)
        + "<SignedInfo>"
        + literal(f'<CanonicalizationMethod Algorithm="{ALG_C14N_EXC}"/>')
        + literal(f'<SignatureMethod Algorithm="{ALG_RSA_SHA256}"/>')
        + literal(f'<Reference URI="#{CDC_FICTICIO}">')
        + "<Transforms>"
        + literal(f'<Transform Algorithm="{ALG_ENVELOPED}"/>')
        + literal(f'<Transform Algorithm="{ALG_C14N_EXC}"/>')
        + "</Transforms>"
        + literal(f'<DigestMethod Algorithm="{ALG_SHA256}"/>')
        + "<DigestValue>[A-Za-z0-9+/]{43}=</DigestValue>"
        + "</Reference>"
        + "</SignedInfo>"
        + "<SignatureValue>[A-Za-z0-9+/]+={0,2}</SignatureValue>"
        + "<KeyInfo><X509Data><X509Certificate>"
        + "(?:[A-Za-z0-9+/]{64}\n)*[A-Za-z0-9+/=]{1,64}\n"
        + "</X509Certificate></X509Data></KeyInfo>"
        + "</Signature>"
    )
    firma_texto = _subcadena(salida, "<Signature", "</Signature>")
    assert re.fullmatch(patron, firma_texto), firma_texto
    assert firma_texto.count("<X509Certificate>") == 1
    assert "KeyValue" not in firma_texto
    assert "KeyName" not in firma_texto


def test_digest_es_sha256_de_c14n_exclusiva_del_nodo(firmador):
    con_comentario = _doc_sifen(contenido_de="<v>1</v><!--c-->")
    sin_comentario = _doc_sifen(contenido_de="<v>1</v>")

    salida = firmador.sign(con_comentario, CDC_FICTICIO)
    de = _arbol(salida).find(f"{{{NS_SIFEN}}}DE")

    assert f'xmlns:xsi="{NS_XSI}"' in salida
    assert _digest_de_salida(salida) == _digest_esperado(de)
    otra = firmador.sign(sin_comentario, CDC_FICTICIO)
    assert _digest_de_salida(salida) == _digest_de_salida(otra)


def test_firma_verifica_con_verificadores_independientes(firmador, material_prueba):
    salida = firmador.sign(_doc_sifen(), CDC_FICTICIO)

    firmado = _verificar_xmldsig(salida, material_prueba)
    assert etree.QName(firmado).localname == "DE"
    assert firmado.get("Id") == CDC_FICTICIO
    _verificar_rsa(salida, material_prueba)


def test_x509certificate_es_cuerpo_pem_del_certificado_firmante(
    firmador, material_prueba, especiales
):
    salida = firmador.sign(_doc_sifen(), CDC_FICTICIO)
    certificados = _arbol(salida).findall(f".//{{{NS_DS}}}X509Certificate")
    assert [c.text for c in certificados] == [material_prueba.cuerpo_pem]
    assert not material_prueba.cuerpo_pem.startswith("\n")
    assert material_prueba.cuerpo_pem.endswith("\n")
    assert "\r" not in salida

    con_ca = get_pkcs12_signer(especiales.con_ca, PASSWORD).sign(
        _doc_sifen(), CDC_FICTICIO
    )
    certificados = _arbol(con_ca).findall(f".//{{{NS_DS}}}X509Certificate")
    assert [c.text for c in certificados] == [especiales.con_ca_material.cuerpo_pem]
    assert especiales.ca_cuerpo_pem not in con_ca
    _verificar_xmldsig(con_ca, especiales.con_ca_material)


def test_valores_base64_en_una_linea(firmador):
    salida = firmador.sign(_doc_sifen(), CDC_FICTICIO)
    raiz = _arbol(salida)
    digest = raiz.find(f".//{{{NS_DS}}}DigestValue").text
    valor = raiz.find(f".//{{{NS_DS}}}SignatureValue").text

    assert not re.search(r"\s", digest)
    assert not re.search(r"\s", valor)
    assert len(base64.b64decode(digest, validate=True)) == 32
    assert len(base64.b64decode(valor, validate=True)) == 256


def test_salida_determinista(pfx_prueba):
    documento = _doc_sifen()
    primera = get_pkcs12_signer(pfx_prueba, PASSWORD).sign(documento, CDC_FICTICIO)
    segunda = get_pkcs12_signer(pfx_prueba, PASSWORD).sign(documento, CDC_FICTICIO)
    clear_pkcs12_signer_cache()
    tercera = get_pkcs12_signer(pfx_prueba, PASSWORD).sign(documento, CDC_FICTICIO)

    assert primera == segunda == tercera


# ---------------------------------------------------------------------------
# B. Ubicacion
# ---------------------------------------------------------------------------


def test_signature_queda_entre_de_y_gcamfufd(firmador):
    salida = firmador.sign(_doc_sifen(), CDC_FICTICIO)
    assert _hijos(_arbol(salida)) == ["dVerFor", "DE", "Signature", "gCamFuFD"]


def test_signature_es_hermana_inmediata_del_nodo_firmado(firmador, material_prueba):
    documento = '<raiz><a/><nodo Id="n1"><v>1</v></nodo><b/></raiz>'
    salida = firmador.sign(documento, "n1")

    assert _hijos(_arbol(salida)) == ["a", "nodo", "Signature", "b"]
    assert _uri(salida) == "#n1"
    _verificar_xmldsig(salida, material_prueba)


def test_signature_en_evento_anidado(firmador, material_prueba):
    documento = _doc_evento("123")
    assert documento.startswith("<?xml version='1.0' encoding='utf-8'?>\n")

    salida = firmador.sign(documento, "123")
    raiz = _arbol(salida)

    assert _hijos(raiz) == ["rGesEve"]
    assert _hijos(raiz[0]) == ["rEve", "Signature"]
    assert "ds:" not in salida
    assert "<!--" not in salida
    _verificar_xmldsig(salida, material_prueba)

    parser = etree.XMLParser(remove_blank_text=True)
    reparseado = etree.fromstring(salida.encode("utf-8"), parser=parser)
    compacto = etree.tostring(reparseado, xml_declaration=True, encoding="UTF-8")
    signxml.XMLVerifier().verify(
        compacto, x509_cert=material_prueba.cert_pem, id_attribute="Id"
    )


def test_nodo_firmado_raiz_recibe_signature_al_final(firmador, material_prueba):
    salida = firmador.sign("<root Id='doc'><child /></root>", "doc")

    assert _hijos(_arbol(salida)) == ["child", "Signature"]
    assert _uri(salida) == "#doc"
    _verificar_xmldsig(salida, material_prueba)


@pytest.mark.parametrize("doc_id", ["", None])
@pytest.mark.parametrize(
    ("documento", "uri"),
    [
        ("<r><n Id='x'><v>1</v></n></r>", ""),
        ("<r Id='root1'><n><v>1</v></n></r>", "#root1"),
        ("<r ID='mayus'><n/></r>", "#mayus"),
        ("<r id='minus'><n/></r>", ""),
    ],
)
def test_doc_id_vacio_firma_documento_completo(
    firmador, material_prueba, documento, uri, doc_id
):
    salida = firmador.sign(documento, doc_id)
    raiz = _arbol(salida)

    assert _uri(salida) == uri
    assert etree.QName(raiz[-1]).localname == "Signature"
    assert len(_firmas(salida)) == 1
    _verificar_xmldsig(salida, material_prueba, id_attribute=None)


@pytest.mark.parametrize(
    "atributo",
    ["id", "ID", "xml:id"],
)
def test_id_en_variante_de_atributo(firmador, material_prueba, atributo):
    documento = f"<r><n {atributo}='x'><v>1</v></n><z/></r>"
    try:
        salida = firmador.sign(documento, "x")
    except SifenSignatureError:
        return
    raiz = _arbol(salida)
    assert _uri(salida) == "#x"
    assert etree.QName(raiz[-1]).localname == "Signature"
    _verificar_xmldsig(salida, material_prueba, id_attribute=None)


@pytest.mark.parametrize("tipo", ["cancelacion", "inutilizacion"])
def test_builders_de_eventos_firman_con_el_signer_real(
    pfx_prueba, material_prueba, tipo
):
    builder = pytest.importorskip("kilasifen.infrastructure.sifen.typed_event_builder")
    firmado_en = datetime(2026, 4, 25, 10, 0, 0)
    if tipo == "cancelacion":
        salida = builder.build_signed_cancel_event_group_xml(
            cdc=CDC_FICTICIO,
            motivo="Error de carga en datos",
            signed_at=firmado_en,
            event_id="123",
            certificate_bytes=pfx_prueba,
            certificate_password=PASSWORD,
        )
    else:
        salida = builder.build_signed_inutilization_event_group_xml(
            timbrado="12345678",
            i_tide=1,
            establishment="1",
            point="1",
            numero_desde=1,
            numero_hasta=3,
            motivo="Saltos de numeracion",
            signed_at=firmado_en,
            event_id="124",
            certificate_bytes=pfx_prueba,
            certificate_password=PASSWORD,
        )

    raiz = _arbol(salida)
    r_ges_eve = raiz.find(f"{{{NS_SIFEN}}}rGesEve")
    assert _hijos(r_ges_eve) == ["rEve", "Signature"]
    signxml.XMLVerifier().verify(
        salida.encode("utf-8"), x509_cert=material_prueba.cert_pem, id_attribute="Id"
    )


# ---------------------------------------------------------------------------
# C. Firmas previas
# ---------------------------------------------------------------------------


def test_reemplaza_firma_de_relleno_de_la_muestra(
    pfx_prueba, material_prueba, rde_muestra
):
    entrada = rde_muestra.to_xml()
    previas = etree.fromstring(entrada.encode("utf-8")).findall(
        f".//{{{NS_DS}}}DigestValue"
    )
    assert previas, "la muestra debe traer una Signature de relleno"

    salida = firma.sign_xml(entrada, pfx_prueba, PASSWORD, rde_muestra.DE.Id)

    assert len(_firmas(salida)) == 1
    assert _digest_de_salida(salida) not in {nodo.text for nodo in previas}
    _verificar_xmldsig(salida, material_prueba)
    assert _hijos(_arbol(salida)) == ["dVerFor", "DE", "Signature", "gCamFuFD"]
    assert "ns1:" not in salida
    assert "ns0:" in salida


def test_elimina_firmas_previas_en_cualquier_nivel(firmador, material_prueba):
    previa = "<{p}Signature xmlns{d}='{ns}'><{p}SignedInfo/></{p}Signature>"
    con_ds = previa.format(p="ds:", d=":ds", ns=NS_DS)
    con_otro = previa.format(p="otro:", d=":otro", ns=NS_DS)
    por_defecto = previa.format(p="", d="", ns=NS_DS)
    documento = (
        _doc_sifen(contenido_de=f"<v>1</v>{con_ds}")
        .replace("</DE>", f"</DE>{con_otro}")
        .replace("</rDE>", f"{por_defecto}</rDE>")
    )

    salida = firmador.sign(documento, CDC_FICTICIO)

    assert len(_firmas(salida)) == 1
    assert _hijos(_arbol(salida)) == ["dVerFor", "DE", "Signature", "gCamFuFD"]
    limpia = firmador.sign(_doc_sifen(contenido_de="<v>1</v>"), CDC_FICTICIO)
    assert _digest_de_salida(salida) == _digest_de_salida(limpia)
    _verificar_xmldsig(salida, material_prueba)


def test_refirmar_es_idempotente(pfx_prueba, rde_muestra):
    firmador = get_pkcs12_signer(pfx_prueba, PASSWORD)
    doc_id = rde_muestra.DE.Id
    una_vez = firmador.sign(rde_muestra.to_xml(), doc_id)
    assert firmador.sign(una_vez, doc_id) == una_vez

    minima = firmador.sign(_doc_sifen(), CDC_FICTICIO)
    assert firmador.sign(minima, CDC_FICTICIO) == minima


@pytest.mark.parametrize(
    ("documento", "doc_id", "esperado"),
    [
        (
            "<r><Signature>keep</Signature><n Id='x'/><z/></r>",
            "x",
            ["Signature", "n", FIRMA_DS, "z"],
        ),
        (
            "<r><n Id='x'/><Signature>keep</Signature></r>",
            "x",
            ["n", FIRMA_DS, "Signature"],
        ),
        (
            "<r><n Id='x'><v>1</v><Signature>keep</Signature></n></r>",
            "x",
            ["n", FIRMA_DS],
        ),
        (
            _doc_sifen().replace("</rDE>", "<Signature>keep</Signature></rDE>"),
            CDC_FICTICIO,
            [
                f"{{{NS_SIFEN}}}dVerFor",
                f"{{{NS_SIFEN}}}DE",
                FIRMA_DS,
                f"{{{NS_SIFEN}}}gCamFuFD",
                f"{{{NS_SIFEN}}}Signature",
            ],
        ),
    ],
    ids=["ajena_antes", "ajena_despues", "ajena_dentro", "ajena_sifen"],
)
def test_signature_ajena_no_se_mueve_ni_se_toma_como_firma(
    firmador, material_prueba, documento, doc_id, esperado
):
    salida = firmador.sign(documento, doc_id)
    raiz = _arbol(salida)

    assert _etiquetas(raiz) == esperado
    assert len(_firmas(salida)) == 1
    ajenas = [
        nodo
        for nodo in raiz.iter()
        if isinstance(nodo.tag, str)
        and etree.QName(nodo).localname == "Signature"
        and nodo.tag != FIRMA_DS
    ]
    assert [nodo.text for nodo in ajenas] == ["keep"]
    if "<v>1</v><Signature>keep" in documento:
        assert _etiquetas(raiz[0]) == ["v", "Signature"]
    _verificar_xmldsig(salida, material_prueba)


def test_cola_de_firma_previa_se_descarta(firmador):
    documento = (
        f"<r><n Id='x'><v>1</v></n><ds:Signature xmlns:ds='{NS_DS}'/>TAIL<z/></r>"
    )
    salida = firmador.sign(documento, "x")

    assert "TAIL" not in salida
    assert _hijos(_arbol(salida)) == ["n", "Signature", "z"]


# ---------------------------------------------------------------------------
# D. Normalizacion y serializacion
# ---------------------------------------------------------------------------


def _blancos_residuales(salida: str) -> list[str]:
    residuales = []
    for elemento in _arbol(salida).iter(etree.Element):
        for valor in (elemento.text, elemento.tail):
            if valor is not None and valor.isspace():
                residuales.append(elemento.tag)
    return residuales


def test_entrada_indentada_y_compacta_firman_igual(firmador, rde_muestra):
    compacta = _doc_sifen()
    indentada = _indentar(compacta)
    assert indentada != compacta

    salida = firmador.sign(compacta, CDC_FICTICIO)
    assert firmador.sign(indentada, CDC_FICTICIO) == salida
    assert _blancos_residuales(salida) == []

    doc_id = rde_muestra.DE.Id
    con_sangria = firmador.sign(rde_muestra.to_xml(), doc_id)
    sin_sangria = firmador.sign(rde_muestra.to_xml(pretty_print=False), doc_id)
    assert con_sangria == sin_sangria
    assert _blancos_residuales(con_sangria) == []


def test_preserva_prefijos_y_declaraciones(firmador, rde_muestra):
    salida = firmador.sign(_doc_sifen(), CDC_FICTICIO)
    assert "<dCarQR>" in salida
    assert not re.search(r"<\w+:", salida)
    assert salida.startswith(f'<rDE xmlns="{NS_SIFEN}" xmlns:xsi="{NS_XSI}">')

    con_prefijo = firmador.sign(rde_muestra.to_xml(), rde_muestra.DE.Id)
    assert "<ns0:rDE" in con_prefijo
    assert "<ns0:dCarQR>" in con_prefijo


def test_textos_no_blancos_intactos_y_blancos_unicode_eliminados(firmador):
    contenido = (
        "<t1>  x  </t1>"
        "<t2>x\ny</t2>"
        "<t3>Factura electrónica</t3>"
        '<t4 a="  "/>'
        "<t5>\u200b</t5>"
        "<t6>\u00a0\u2003</t6>"
        "<t7> </t7>"
        "<t8>\t\n</t8>"
    )
    salida = firmador.sign(_doc_sifen(contenido_de=contenido), CDC_FICTICIO)

    assert "<t1>  x  </t1>" in salida
    assert "<t2>x\ny</t2>" in salida
    assert "<t3>Factura electrónica</t3>" in salida
    assert '<t4 a="  "/>' in salida
    assert "<t5>\u200b</t5>" in salida
    assert "<t6/>" in salida
    assert "<t7/>" in salida
    assert "<t8/>" in salida
    assert "nVersion=150&amp;Id=1</dCarQR>" in salida


def test_salida_sin_declaracion_xml(firmador):
    cuerpo = "<!--antes--><?instruccion antes?>" + _doc_sifen() + "<!--despues-->"
    estilo_xsdata = '<?xml version="1.0" encoding="UTF-8"?>\n' + cuerpo
    variantes = [
        estilo_xsdata,
        "<?xml version='1.0' encoding='UTF-8'?>\n" + cuerpo,
        "<?xml version='1.0' encoding='utf-8'?>\n" + cuerpo,
        cuerpo,
        codecs.BOM_UTF8 + estilo_xsdata.encode("utf-8"),
        "\ufeff" + cuerpo,
    ]

    salidas = [firmador.sign(variante, CDC_FICTICIO) for variante in variantes]

    for salida in salidas:
        assert isinstance(salida, str)
        assert salida.startswith("<rDE")
        assert "<?xml" not in salida
        assert "\ufeff" not in salida
        assert not salida.endswith("\n")
        assert "antes" not in salida
        assert "despues" not in salida
    assert len(set(salidas)) == 1


def test_comentarios_internos_se_conservan(firmador, material_prueba):
    documento = _doc_sifen(contenido_de="<a>1</a><!--nota-->  <b>2</b>")
    salida = firmador.sign(documento, CDC_FICTICIO)

    assert "<a>1</a><!--nota-->  <b>2</b>" in salida
    _verificar_xmldsig(salida, material_prueba)


def test_cdata_se_serializa_como_texto_escapado(firmador):
    documento = _doc_sifen(contenido_de="<v><![CDATA[ <a> ]]></v>")
    salida = firmador.sign(documento, CDC_FICTICIO)

    assert "<v> &lt;a&gt; </v>" in salida
    assert "CDATA" not in salida


# ---------------------------------------------------------------------------
# E. Tipos de entrada
# ---------------------------------------------------------------------------


def test_str_bytes_y_elemento_lxml_equivalentes(firmador):
    texto = _doc_sifen()
    elemento = etree.fromstring(texto.encode("utf-8"))

    desde_texto = firmador.sign(texto, CDC_FICTICIO)
    assert firmador.sign(texto.encode("utf-8"), CDC_FICTICIO) == desde_texto
    assert firmador.sign(elemento, CDC_FICTICIO) == desde_texto
    assert elemento.find(f".//{{{NS_DS}}}Signature") is None
    assert elemento.find(f".//{{{NS_DS}}}SignatureValue") is None


def test_no_modifica_el_arbol_lxml_del_llamador(firmador):
    previa = f"<ds:Signature xmlns:ds='{NS_DS}'><ds:SignedInfo/></ds:Signature>"
    texto = _indentar(_doc_sifen().replace("</DE>", f"</DE>{previa}"))
    elemento = etree.fromstring(texto.encode("utf-8"))
    antes = etree.tostring(elemento)

    firmador.sign(elemento, CDC_FICTICIO)

    assert etree.tostring(elemento) == antes


def test_bytes_con_codificacion_declarada_latin1(firmador):
    texto = _doc_sifen(contenido_de="<dNomRec>ÑANDUTÍ</dNomRec>")
    datos = ('<?xml version="1.0" encoding="ISO-8859-1"?>\n' + texto).encode(
        "iso-8859-1"
    )

    salida = firmador.sign(datos, CDC_FICTICIO)

    assert "<dNomRec>ÑANDUTÍ</dNomRec>" in salida
    assert salida == firmador.sign(texto, CDC_FICTICIO)


@pytest.mark.parametrize("entrada", [123, None])
def test_tipo_de_entrada_no_soportado(firmador, entrada):
    with pytest.raises(SifenSignatureError) as excinfo:
        firmador.sign(entrada, CDC_FICTICIO)

    assert str(excinfo.value) == MENSAJE_FIRMA
    assert excinfo.value.__cause__ is not None


# ---------------------------------------------------------------------------
# F. PKCS12 y contrasenas
# ---------------------------------------------------------------------------


def test_password_str_y_bytes_equivalentes(pfx_prueba):
    con_texto = get_pkcs12_signer(pfx_prueba, PASSWORD)
    con_bytes = get_pkcs12_signer(pfx_prueba, PASSWORD.encode("utf-8"))

    assert con_texto is con_bytes
    documento = _doc_sifen()
    assert con_texto.sign(documento, CDC_FICTICIO) == con_bytes.sign(
        documento, CDC_FICTICIO
    )


def test_password_no_ascii_se_codifica_utf8(especiales):
    salida = firma.sign_xml(
        _doc_sifen(), especiales.con_password_unicode, "contraseña", CDC_FICTICIO
    )
    _verificar_xmldsig(salida, especiales.sin_cifrar_material)


@pytest.mark.parametrize("password", [None, "", b""])
def test_pkcs12_sin_cifrar_acepta_none_y_vacio(especiales, password):
    salida = get_pkcs12_signer(especiales.sin_cifrar, password).sign(
        _doc_sifen(), CDC_FICTICIO
    )
    _verificar_xmldsig(salida, especiales.sin_cifrar_material)


@pytest.mark.parametrize("password", ["incorrecta", None])
def test_password_incorrecta(pfx_prueba, password):
    with pytest.raises(SifenSignatureError) as excinfo:
        get_pkcs12_signer(pfx_prueba, password)

    assert str(excinfo.value) == MENSAJE_CARGA
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_pkcs12_invalido():
    with pytest.raises(SifenSignatureError) as excinfo:
        firma.sign_xml(_doc_sifen(), b"invalid-pkcs12", PASSWORD, CDC_FICTICIO)

    assert str(excinfo.value) == MENSAJE_CARGA
    assert isinstance(excinfo.value.__cause__, ValueError)


@pytest.mark.parametrize("contenedor", ["solo_certificado", "solo_clave"])
def test_pkcs12_incompleto_falla_al_construir(especiales, contenedor):
    with pytest.raises(SifenSignatureError) as excinfo:
        get_pkcs12_signer(getattr(especiales, contenedor), None)

    assert str(excinfo.value) == MENSAJE_CARGA
    assert excinfo.value.__cause__ is not None


def test_clave_no_rsa_falla(especiales):
    with pytest.raises(SifenSignatureError):
        firma.sign_xml(_doc_sifen(), especiales.clave_ec, PASSWORD, CDC_FICTICIO)


@pytest.mark.parametrize("envoltura", [bytearray, memoryview])
def test_pkcs12_bytearray_o_memoryview_se_acepta(pfx_prueba, envoltura):
    firmador = get_pkcs12_signer(envoltura(pfx_prueba), PASSWORD)

    assert firmador is get_pkcs12_signer(pfx_prueba, PASSWORD)
    assert "SignatureValue" in firmador.sign(_doc_sifen(), CDC_FICTICIO)


def test_password_no_codificable_falla_con_error_de_firma(pfx_prueba):
    with pytest.raises(SifenSignatureError) as excinfo:
        get_pkcs12_signer(pfx_prueba, "clave\ud800")

    assert str(excinfo.value) == MENSAJE_CARGA
    assert isinstance(excinfo.value.__cause__, UnicodeEncodeError)


# ---------------------------------------------------------------------------
# G. Errores del documento y seguridad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "documento",
    ["", b"", "<raiz>", "no es xml", "<a></b>", "\n<?xml version='1.0'?><a/>"],
)
def test_xml_mal_formado_o_vacio(firmador, documento):
    with pytest.raises(SifenSignatureError) as excinfo:
        firmador.sign(documento, "x")

    assert str(excinfo.value) == MENSAJE_FIRMA
    assert excinfo.value.__cause__ is not None


def test_doc_id_inexistente(firmador):
    with pytest.raises(SifenSignatureError):
        firmador.sign(_doc_sifen(), "99999999999999999999999999999999999999999999")


def test_doc_id_duplicado(firmador):
    documento = "<r><a Id='x'><v>1</v></a><b Id='x'><v>2</v></b></r>"
    with pytest.raises(SifenSignatureError):
        firmador.sign(documento, "x")


def test_entidad_externa_no_se_resuelve(firmador, tmp_path):
    secreto = "contenido-secreto-de-prueba"
    archivo = tmp_path / "secreto.txt"
    archivo.write_text(secreto, encoding="utf-8")
    documento = (
        f'<!DOCTYPE r [<!ENTITY s SYSTEM "{archivo.as_uri()}">]>'
        "<r><n Id='x'>&s;</n></r>"
    )

    try:
        salida = firmador.sign(documento, "x")
    except SifenSignatureError:
        return
    assert secreto not in salida


def test_documento_con_doctype_se_rechaza(firmador):
    documento = "<!DOCTYPE r [<!ENTITY e \"interna\">]><r><n Id='x'>&e;</n></r>"
    with pytest.raises(SifenSignatureError) as excinfo:
        firmador.sign(documento, "x")

    assert str(excinfo.value) == MENSAJE_FIRMA
    assert excinfo.value.__cause__ is not None


@pytest.mark.parametrize("con_firma_previa", [False, True])
def test_prefijo_ds_en_ancestro_no_corrompe_firma(
    firmador, material_prueba, con_firma_previa
):
    previa = "<ds:Signature><ds:SignedInfo/></ds:Signature>" if con_firma_previa else ""
    documento = _doc_sifen().replace(
        f'xmlns:xsi="{NS_XSI}"', f'xmlns:xsi="{NS_XSI}" xmlns:ds="{NS_DS}"'
    )
    documento = documento.replace("</DE>", f"</DE>{previa}")

    try:
        salida = firmador.sign(documento, CDC_FICTICIO)
    except SifenSignatureError:
        return
    assert len(_firmas(salida)) == 1
    assert APERTURA_FIRMA in salida
    assert "<ds:Signature" not in salida
    assert _hijos(_arbol(salida)) == ["dVerFor", "DE", "Signature", "gCamFuFD"]
    _verificar_xmldsig(salida, material_prueba)


def test_envuelve_errores_sin_doble_envoltura(monkeypatch, pfx_prueba):
    def falla_valor(*args, **kwargs):
        raise ValueError("pkcs12 roto")

    monkeypatch.setattr(CARGADOR, falla_valor)
    with pytest.raises(SifenSignatureError) as excinfo:
        get_pkcs12_signer(pfx_prueba, PASSWORD)
    assert isinstance(excinfo.value.__cause__, ValueError)

    propio = SifenSignatureError("ya tipado")

    def falla_tipada(*args, **kwargs):
        raise propio

    monkeypatch.setattr(CARGADOR, falla_tipada)
    with pytest.raises(SifenSignatureError) as excinfo:
        get_pkcs12_signer(pfx_prueba, PASSWORD)
    assert excinfo.value is propio


# ---------------------------------------------------------------------------
# H. Cache y concurrencia
# ---------------------------------------------------------------------------


def test_reutiliza_pkcs12_en_firmas_sucesivas(monkeypatch, pfx_prueba, rde_muestra):
    llamadas = _contar_cargas(monkeypatch)
    entrada = rde_muestra.to_xml()

    primera = firma.sign_xml(entrada, pfx_prueba, PASSWORD, rde_muestra.DE.Id)
    segunda = firma.sign_xml(entrada, pfx_prueba, PASSWORD, rde_muestra.DE.Id)

    assert len(llamadas) == 1
    assert primera == segunda
    assert "SignatureValue" in primera


def test_misma_instancia_por_contenido(pfx_prueba):
    copia = bytes(bytearray(pfx_prueba))
    assert copia is not pfx_prueba
    assert get_pkcs12_signer(pfx_prueba, PASSWORD) is get_pkcs12_signer(copia, PASSWORD)


def test_cache_lru_de_ocho_entradas(monkeypatch, especiales):
    contenedores = _generar_pkcs12_distintos(especiales, 9)
    llamadas = _contar_cargas(monkeypatch)

    firmadores = [get_pkcs12_signer(c, PASSWORD) for c in contenedores[:8]]
    assert len(llamadas) == 8

    assert get_pkcs12_signer(contenedores[0], PASSWORD) is firmadores[0]
    assert len(llamadas) == 8

    get_pkcs12_signer(contenedores[8], PASSWORD)
    assert len(llamadas) == 9

    assert get_pkcs12_signer(contenedores[0], PASSWORD) is firmadores[0]
    assert len(llamadas) == 9

    nuevo = get_pkcs12_signer(contenedores[1], PASSWORD)
    assert len(llamadas) == 10
    assert nuevo is not firmadores[1]


def test_fallos_no_se_cachean(monkeypatch, pfx_prueba):
    llamadas = _contar_cargas(monkeypatch)

    for _ in range(2):
        with pytest.raises(SifenSignatureError):
            get_pkcs12_signer(pfx_prueba, "incorrecta")
    assert len(llamadas) == 2

    primero = get_pkcs12_signer(pfx_prueba, PASSWORD)
    assert get_pkcs12_signer(pfx_prueba, PASSWORD) is primero
    assert len(llamadas) == 3


def test_clear_fuerza_nueva_decodificacion(monkeypatch, pfx_prueba):
    llamadas = _contar_cargas(monkeypatch)

    antes = get_pkcs12_signer(pfx_prueba, PASSWORD)
    clear_pkcs12_signer_cache()
    despues = get_pkcs12_signer(pfx_prueba, PASSWORD)

    assert antes is not despues
    assert len(llamadas) == 2
    assert "SignatureValue" in antes.sign(_doc_sifen(), CDC_FICTICIO)


def _en_paralelo(tarea, cantidad: int = 8) -> list:
    barrera = threading.Barrier(cantidad)
    resultados: list = [None] * cantidad
    errores: list[BaseException] = []

    def trabajo(indice: int) -> None:
        try:
            barrera.wait()
            resultados[indice] = tarea()
        except BaseException as exc:  # pragma: no cover - solo ante fallos
            errores.append(exc)

    hilos = [threading.Thread(target=trabajo, args=(i,)) for i in range(cantidad)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    assert errores == []
    return resultados


def test_firma_concurrente_con_el_mismo_signer(firmador, material_prueba):
    documento = _doc_sifen()
    resultados = _en_paralelo(lambda: firmador.sign(documento, CDC_FICTICIO))

    assert len(set(resultados)) == 1
    _verificar_xmldsig(resultados[0], material_prueba)


def test_acceso_concurrente_a_la_cache(pfx_prueba, material_prueba):
    documento = _doc_sifen()
    resultados = _en_paralelo(
        lambda: get_pkcs12_signer(pfx_prueba, PASSWORD).sign(documento, CDC_FICTICIO)
    )

    assert len(set(resultados)) == 1
    _verificar_xmldsig(resultados[0], material_prueba)


def test_import_no_carga_dependencias_pesadas():
    comprobar = (
        "import sys\n"
        "import kilasifen.engine.sdk.signer\n"
        "cargados = [m for m in ('signxml', 'cryptography') if m in sys.modules]\n"
        "assert cargados == [], cargados\n"
    )
    bloqueadas = (
        "import sys\n"
        "sys.modules['signxml'] = None\n"
        "sys.modules['cryptography'] = None\n"
        "import kilasifen.engine.sdk.signer as modulo\n"
        "assert callable(modulo.get_pkcs12_signer)\n"
    )
    for codigo in (comprobar, bloqueadas):
        resultado = subprocess.run(
            [sys.executable, "-c", codigo],
            cwd=RAIZ_REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert resultado.returncode == 0, resultado.stderr


# ---------------------------------------------------------------------------
# I. Fachada y mixin
# ---------------------------------------------------------------------------


def test_mixin_firma_igual_que_la_fachada(pfx_prueba, rde_muestra):
    entrada = rde_muestra.to_xml()
    doc_id = rde_muestra.DE.Id

    assert rde_muestra.sign_xml(entrada, pfx_prueba, PASSWORD, doc_id) == (
        firma.sign_xml(entrada, pfx_prueba, PASSWORD, doc_id)
    )


def test_mixin_sin_xml_firma_la_instancia(pfx_prueba, rde_muestra):
    doc_id = rde_muestra.DE.Id
    desde_mixin = rde_muestra.sign_xml(None, pfx_prueba, PASSWORD, doc_id)

    compacta = rde_muestra.to_xml(pretty_print=False)
    assert desde_mixin == firma.sign_xml(compacta, pfx_prueba, PASSWORD, doc_id)
    assert desde_mixin == firma.sign_xml(
        rde_muestra.to_xml(), pfx_prueba, PASSWORD, doc_id
    )


def test_fachada_delega_en_el_signer(pfx_prueba):
    documento = _doc_sifen()
    assert firma.sign_xml(documento, pfx_prueba, PASSWORD, CDC_FICTICIO) == (
        get_pkcs12_signer(pfx_prueba, PASSWORD).sign(documento, CDC_FICTICIO)
    )


# ---------------------------------------------------------------------------
# J. Compatibilidad con goldens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", GOLDENS, ids=[ruta.stem for ruta in GOLDENS])
def test_refirmar_golden_preserva_payload_y_signedinfo(firmador, material_prueba, ruta):
    datos = ruta.read_bytes()
    texto_golden = datos.decode("utf-8")
    doc_id = etree.fromstring(datos).find(f"{{{NS_SIFEN}}}DE").get("Id")

    salida = firmador.sign(datos, doc_id)

    assert _sin_signature(salida) == _sin_signature(texto_golden)
    assert _subcadena(salida, "<SignedInfo>", "</SignedInfo>") == _subcadena(
        texto_golden, "<SignedInfo>", "</SignedInfo>"
    )
    _verificar_xmldsig(salida, material_prueba)
