"""Prueba real de KilaSifen contra el ambiente de TEST del SIFEN.

Arma, firma y transmite documentos por el mismo camino que el worker de la
plataforma: contrato tipado de la API (``FacturaCreateRequest`` y las de NC y
ND), numeracion y ``dCodSeg`` como ``DocumentService``,
``KilaSifenPayloadMapper`` y ``KilaSifenEmissionEngine`` hasta siRecepDE.
Despues consulta por CDC cada documento aprobado y genera su KuDE. Los eventos
salen de los mismos constructores firmados que usa ``EventService`` y viajan
por ``KilaSifenEventGateway``. Sigue la Guia de Pruebas de la DNIT (feb/2026,
§2): timbrado de prueba = RUC, CSC generico y el literal de prueba en la razon
social del emisor y en el primer item.

SOLO AMBIENTE DE TEST. Antes del primer envio el proceso:

- fija ``KILA_SIFEN_SIFEN_ENVIRONMENT=test`` y
  ``KILA_SIFEN_ENABLE_PRODUCTION=false``;
- borra la tabla de direcciones de produccion (``ENDPOINTS[PRODUCCION]``), asi
  que pedirla falla antes de abrir un socket;
- hace pasar todo envio HTTP por un control que rechaza cualquier host que no
  sea ``sifen-test.set.gov.py``.

La contrasena del certificado nunca se acepta por argumentos ni por variables
de entorno, no se imprime y no se escribe en disco. Se lee del Administrador
de credenciales de Windows (credencial generica ``kilasifen-sifen-test``, que
el titular guarda una vez con
``cmdkey /generic:kilasifen-sifen-test /user:sifen-test /pass``) o, si no
esta, se pide por teclado (``getpass``). Ningun envio se repite a ciegas: ante
un resultado incierto solo se consulta el CDC, y un DE rechazado con un 0160
suelto solo vuelve a viajar (el mismo rDE firmado) si la consulta responde
0420 (regla 6 de CLAUDE.md).

Uso::

    python scripts/sifen_test_smoke.py --dry-run
    python scripts/sifen_test_smoke.py --p12 RUTA [--solo-ruc] [--si]
    python scripts/sifen_test_smoke.py --p12 RUTA --ronda2 CARPETA_RONDA_1 [--si]

``--dry-run`` arma y valida contra el XSD los XML sin certificado y sin red;
``--solo-ruc`` solo prueba la comunicacion con una consulta RUC; ``--si`` no
pide confirmacion antes de enviar. La ronda 1 envia tres facturas; la ronda 2
toma de la carpeta de la ronda 1 los CDC aprobados y envia una nota de credito
y una de debito sobre F1, cancela F2 e inutiliza dos numeros. Los resultados,
con cada pedido y respuesta HTTP, quedan en ``.sifen-test/runs/<fecha-hora>/``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests.adapters
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from kilasifen.api.schemas.documents import (
    FacturaCreateRequest,
    NotaCreditoCreateRequest,
    NotaDebitoCreateRequest,
)
from kilasifen.application.documents.fiscal_preflight import (
    check_emission_date,
    resolve_security_code,
)
from kilasifen.application.events.attempts import (
    CANCEL_EVENT_TYPE,
    INUTILIZATION_EVENT_TYPE,
)
from kilasifen.config import get_settings
from kilasifen.domain.common.paraguay_time import (
    format_sifen_datetime,
    paraguay_now,
    to_paraguay_wall_time,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.fiscal_profile import fiscal_profile_from_dict
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.models import Event
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import (
    SifenRequestNotSentError,
    SifenTransportError,
)
from kilasifen.engine.transmision import config as sifen_config
from kilasifen.infrastructure.kude.pdf_renderer import render_kude_pdf
from kilasifen.infrastructure.sifen.engine import KilaSifenEmissionEngine
from kilasifen.infrastructure.sifen.event import KilaSifenEventGateway
from kilasifen.infrastructure.sifen.mapper import KilaSifenPayloadMapper
from kilasifen.infrastructure.sifen.query import KilaSifenQueryGateway
from kilasifen.infrastructure.sifen.typed_event_builder import (
    build_signed_cancel_event_group_xml,
    build_signed_inutilization_event_group_xml,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / ".sifen-test" / "config.json"
TEST_HOST = "sifen-test.set.gov.py"
CREDENCIAL_WINDOWS = "kilasifen-sifen-test"
SIFEN_NS = "{http://ekuatia.set.gov.py/sifen/xsd}"
APPROVED = {"approved", "approved_with_observation"}
#: El ambiente de pruebas responde a veces 0160 "XML Mal Formado" (HTTP 400,
#: rRetEnviDe) o corta la conexion ante pedidos validos: el mismo request
#: paso segundos despues. Las consultas se repiten; un DE no (ver
#: ``_enviar_escenario``).
INTENTOS = 4
PAUSA_SEGUNDOS = 5
#: Contrato tipado de cada tipo de documento: (pedido de la API, clave del
#: pedido, contrato guardado, document_type), como los routers de la API.
TIPOS = {
    "factura": (FacturaCreateRequest, "factura", "factura_v1", "factura"),
    "nota_credito": (
        NotaCreditoCreateRequest,
        "nota_credito",
        "nota_credito_v1",
        "nota_credito",
    ),
    "nota_debito": (
        NotaDebitoCreateRequest,
        "nota_debito",
        "nota_debito_v1",
        "nota_debito",
    ),
}
TOTAL_FIELDS = (
    "dSubExe",
    "dSubExo",
    "dSub5",
    "dSub10",
    "dTotOpe",
    "dTotGralOpe",
    "dIVA5",
    "dIVA10",
    "dTotIVA",
    "dBaseGrav5",
    "dBaseGrav10",
    "dTBasGraIVA",
)


# --- Candados: nada sale hacia produccion -----------------------------------


def _instalar_candados(trafico: Path | None = None) -> None:
    """Deja el proceso sin forma de hablar con el SIFEN de produccion.

    Con ``trafico`` cada pedido y respuesta HTTP se guarda en esa carpeta
    (cuerpos XML y codigo HTTP; el certificado viaja en el TLS, no en ellos).
    """

    os.environ["KILA_SIFEN_SIFEN_ENVIRONMENT"] = "test"
    os.environ["KILA_SIFEN_ENABLE_PRODUCTION"] = "false"
    get_settings.cache_clear()
    settings = get_settings()
    if settings.sifen_environment != "test" or settings.enable_production:
        raise SystemExit("La configuración no es de TEST: abortado.")

    sifen_config.ENDPOINTS.pop(sifen_config.PRODUCCION, None)
    direcciones = sifen_config.ENDPOINTS[sifen_config.TEST].values()
    if sifen_config.PRODUCCION in sifen_config.ENDPOINTS or any(
        not url.startswith(f"https://{TEST_HOST}/") for url in direcciones
    ):
        raise SystemExit("Las direcciones no son las de sifen-test: abortado.")

    enviar = requests.adapters.HTTPAdapter.send
    contador = iter(range(1, 1000))

    def enviar_solo_a_test(self, request, *args, **kwargs):
        partes = urllib.parse.urlsplit(request.url)
        if partes.hostname != TEST_HOST:
            raise RuntimeError(
                f"BLOQUEADO: sólo se permite {TEST_HOST}, no {partes.hostname}"
            )
        respuesta = enviar(self, request, *args, **kwargs)
        if trafico is not None:
            servicio = partes.path.rsplit("/", 1)[-1].removesuffix(".wsdl")
            prefijo = f"{next(contador):02d}_{servicio}"
            _guardar(trafico, f"{prefijo}_pedido.xml", request.body)
            _guardar(
                trafico,
                f"{prefijo}_respuesta_http{respuesta.status_code}.xml",
                respuesta.content,
            )
        return respuesta

    requests.adapters.HTTPAdapter.send = enviar_solo_a_test


# --- Datos de la prueba -------------------------------------------------------


@dataclass(frozen=True)
class Escenario:
    clave: str
    titulo: str
    datos: dict
    tipo: str = "factura"


def _item(
    codigo: str,
    descripcion: str,
    precio: int,
    *,
    tasa: int = 10,
    afectacion: str = "gravado",
    **extra,
) -> dict:
    return {
        "codigo_interno": codigo,
        "descripcion": descripcion,
        "cantidad": "1",
        "precio_unitario": str(precio),
        "afectacion": afectacion,
        "tasa": tasa,
        **extra,
    }


def _cliente_b2b(config: dict) -> dict:
    receptor = config["receptor_b2b"]
    return {
        "naturaleza": 1,
        "tipo_operacion": 1,
        "ruc": receptor["ruc"],
        "razon_social": receptor["razon_social"],
        "tipo_contribuyente": receptor["tipo_contribuyente"],
    }


def _escenarios(config: dict) -> list[Escenario]:
    """Facturas de la ronda 1 (Guía de Pruebas §4.2: dos ítems o más)."""

    literal = config["emisor"]["literal_ambiente_test"]
    b2b = _cliente_b2b(config)
    innominado = {"naturaleza": 2, "tipo_operacion": 2, "tipo_documento_identidad": 5}
    return [
        Escenario(
            "F1_b2b_iva10_iva5",
            "B2B, IVA 10 % y 5 % con 2 decimales",
            {
                "cliente": b2b,
                "items": [
                    _item("PRUEBA-1", literal, 100000),
                    _item("PRUEBA-2", "Servicio de prueba IVA 5%", 50000, tasa=5),
                ],
            },
        ),
        Escenario(
            "F2_b2c_innominado_centavos",
            "B2C innominado; base + IVA = total + 0,01 en cada ítem",
            {
                "cliente": innominado,
                "items": [
                    _item("PRUEBA-1", literal, 17000),
                    _item("PRUEBA-2", "Producto de prueba B", 11500),
                    _item("PRUEBA-3", "Producto de prueba C", 6000),
                    _item("PRUEBA-4", "Producto de prueba D", 16000, tasa=5),
                ],
            },
        ),
        Escenario(
            "F3_b2b_gravado_parcial_exento",
            "B2B, gravado parcial 30 % (E737 = resto) y exento",
            {
                "cliente": b2b,
                "items": [
                    _item(
                        "PRUEBA-1",
                        literal,
                        100000,
                        afectacion="gravado_parcial",
                        proporcion_gravada="30",
                    ),
                    _item(
                        "PRUEBA-2",
                        "Servicio exento de prueba",
                        20000,
                        tasa=0,
                        afectacion="exento",
                    ),
                ],
            },
        ),
    ]


def _escenarios_ronda2(config: dict, *, cdc_factura: str) -> list[Escenario]:
    """Nota de crédito y de débito asociadas a la factura F1 de la ronda 1."""

    literal = config["emisor"]["literal_ambiente_test"]
    asociado = {"tipo": "electronico", "cdc": cdc_factura}
    return [
        Escenario(
            "NC1_devolucion_parcial_F1",
            "Nota de crédito: devolución parcial de F1 (ítem al 5 %)",
            {
                "cliente": _cliente_b2b(config),
                "motivo_emision": 2,
                "documento_asociado": asociado,
                "items": [_item("PRUEBA-1", literal, 50000, tasa=5)],
            },
            tipo="nota_credito",
        ),
        Escenario(
            "ND1_recupero_costo_F1",
            "Nota de débito: recupero de costo sobre F1",
            {
                "cliente": _cliente_b2b(config),
                "motivo_emision": 6,
                "documento_asociado": asociado,
                "items": [_item("PRUEBA-1", literal, 10000)],
            },
            tipo="nota_debito",
        ),
    ]


def _emisor(config: dict) -> Emitter:
    datos = config["emisor"]
    ahora = datetime.now(timezone.utc)
    return Emitter(
        id="sifen-test-emisor",
        external_id=None,
        ruc=datos["ruc"],
        dv=datos["dv"],
        legal_name=datos["razon_social"],
        # Siempre TEST: el transporte elige el ambiente con este campo.
        tax_environment="test",
        status="active",
        csc=config["csc"]["valor"],
        csc_id=config["csc"]["id"],
        created_at=ahora,
        updated_at=ahora,
        fiscal_profile=fiscal_profile_from_dict(datos["perfil_fiscal"]),
    )


def _timbrado(config: dict, emisor: Emitter) -> Stamping:
    datos = config["timbrado"]
    ahora = datetime.now(timezone.utc)
    return Stamping(
        id="sifen-test-timbrado",
        emitter_id=emisor.id,
        number=datos["numero"],
        start_date=date.fromisoformat(datos["inicio_vigencia"]),
        end_date=None,
        is_active=True,
        status="active",
        created_at=ahora,
        updated_at=ahora,
    )


def _documento(
    escenario: Escenario, *, config: dict, emisor: Emitter, numero: int
) -> Document:
    """Lo que guarda ``DocumentService`` para el POST tipado de la API."""

    pedido_api, clave, contrato_nombre, tipo_documento = TIPOS[escenario.tipo]
    timbrado = config["timbrado"]
    datos = {
        **escenario.datos,
        "establecimiento": timbrado["establecimiento"],
        "punto": timbrado["punto"],
        "fecha_emision": format_sifen_datetime(paraguay_now()),
    }
    pedido = pedido_api.model_validate({clave: datos})
    contrato = getattr(pedido, clave).model_dump(mode="json")
    contrato["numero"] = numero
    avisos = check_emission_date(contrato, now=paraguay_now())
    ahora = datetime.now(timezone.utc)
    return Document(
        id=f"sifen-test-{escenario.clave}",
        emitter_id=emisor.id,
        external_id=None,
        idempotency_key=None,
        document_type=tipo_documento,
        payload_snapshot={
            "generated_xml": None,
            "signed_xml": None,
            "doc_id": None,
            "typed_contract": {"contract": contrato_nombre, "payload": contrato},
        },
        generated_xml=None,
        signed_xml=None,
        sifen_request_xml=None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=None,
        internal_status="queued",
        sifen_status=None,
        sifen_result_code=None,
        sifen_result_message=None,
        created_at=ahora,
        updated_at=ahora,
        establishment=timbrado["establecimiento"],
        point=timbrado["punto"],
        document_number=numero,
        security_code=resolve_security_code(contrato),
        fiscal_warnings=avisos,
    )


# --- Numeracion local ---------------------------------------------------------


class Numeracion:
    """Próximo dNumDoc, guardado antes de cada envío para no repetirlo."""

    def __init__(self, ruta: Path, primero: int) -> None:
        self.ruta = ruta
        self.proximo = primero
        if ruta.exists():
            guardado = json.loads(ruta.read_text("utf-8"))
            self.proximo = int(guardado["proximo_numero"])

    def reservar(self) -> int:
        numero = self.proximo
        self.proximo += 1
        estado = {"proximo_numero": self.proximo}
        self.ruta.write_text(json.dumps(estado, indent=2), "utf-8")
        return numero


# --- Certificado --------------------------------------------------------------


def _clave_de_windows(destino: str) -> str | None:
    """Contraseña de la credencial genérica ``destino`` de Windows, o None."""

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Credencial(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    leer = advapi32.CredReadW
    leer.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credencial)),
    ]
    leer.restype = wintypes.BOOL
    liberar = advapi32.CredFree
    liberar.argtypes = [ctypes.c_void_p]
    puntero = ctypes.POINTER(Credencial)()
    if not leer(destino, 1, 0, ctypes.byref(puntero)):  # 1 = CRED_TYPE_GENERIC
        return None
    try:
        credencial = puntero.contents
        blob = ctypes.string_at(
            credencial.CredentialBlob, credencial.CredentialBlobSize
        )
        return blob.decode("utf-16-le")
    finally:
        liberar(puntero)


def _confirmar(pregunta: str, *, sin_preguntar: bool) -> bool:
    if sin_preguntar:
        return True
    return input(pregunta).strip().lower() in {"si", "sí"}


def _revisar_certificado(
    pfx: bytes, clave: str, ruc: str, *, sin_preguntar: bool
) -> None:
    """Muestra el certificado y corta si no está vigente."""

    try:
        _, certificado, _ = pkcs12.load_key_and_certificates(pfx, clave.encode())
    except ValueError:
        raise SystemExit("No se pudo abrir el .p12: contraseña incorrecta.") from None
    if certificado is None:
        raise SystemExit("El .p12 no trae certificado.")
    sujeto = certificado.subject
    nombres = sujeto.get_attributes_for_oid(NameOID.COMMON_NAME)
    autoridad = certificado.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
    extensiones = certificado.extensions
    try:
        san = str(extensiones.get_extension_for_class(x509.SubjectAlternativeName))
    except x509.ExtensionNotFound:
        san = ""
    try:
        usos = extensiones.get_extension_for_class(x509.ExtendedKeyUsage).value
        client_auth = ExtendedKeyUsageOID.CLIENT_AUTH in usos
    except x509.ExtensionNotFound:
        client_auth = False
    desde = certificado.not_valid_before_utc
    hasta = certificado.not_valid_after_utc
    contiene_ruc = ruc in sujeto.rfc4514_string() or ruc in san
    print("Certificado:")
    print(f"  titular: {nombres[0].value if nombres else '-'}")
    print(f"  emitido por: {autoridad[0].value if autoridad else '-'}")
    print(f"  vigencia: {desde:%Y-%m-%d %H:%M} a {hasta:%Y-%m-%d %H:%M} (UTC)")
    print(f"  clientAuth (TLS mutuo): {'sí' if client_auth else 'NO'}")
    print(f"  menciona el RUC {ruc}: {'sí' if contiene_ruc else 'NO'}")
    if not desde <= datetime.now(timezone.utc) <= hasta:
        raise SystemExit("El certificado no está vigente: no se envía nada.")
    if not contiene_ruc and not _confirmar(
        "El certificado no menciona el RUC del emisor y el SIFEN puede "
        "rechazarlo. Escribí si para seguir igual: ",
        sin_preguntar=sin_preguntar,
    ):
        raise SystemExit("No se envió nada.")


# --- Salida -------------------------------------------------------------------


def _resumen_xml(xml: str) -> dict:
    """Totales y IVA por ítem del XML, tal como viajan."""

    raiz = ET.fromstring(xml.encode("utf-8"))
    resumen: dict = {"totales": {}, "items": []}
    totales = raiz.find(f".//{SIFEN_NS}gTotSub")
    if totales is not None:
        for campo in TOTAL_FIELDS:
            valor = totales.findtext(f"{SIFEN_NS}{campo}")
            if valor is not None:
                resumen["totales"][campo] = valor
    for item in raiz.iter(f"{SIFEN_NS}gCamItem"):
        iva = item.find(f"{SIFEN_NS}gCamIVA")
        datos = {"total": item.findtext(f".//{SIFEN_NS}dTotOpeItem")}
        for campo in ("dBasGravIVA", "dLiqIVAItem", "dBasExe"):
            datos[campo] = None if iva is None else iva.findtext(f"{SIFEN_NS}{campo}")
        resumen["items"].append(datos)
    return resumen


def _imprimir_resumen_xml(resumen: dict) -> None:
    for item in resumen["items"]:
        print(
            f"    ítem {item['total']}: base {item['dBasGravIVA']}, "
            f"IVA {item['dLiqIVAItem']}, exenta {item['dBasExe']}"
        )
    totales = ", ".join(f"{k} {v}" for k, v in resumen["totales"].items())
    print(f"    totales: {totales}")


def _guardar(carpeta: Path, nombre: str, contenido: str | bytes | None) -> None:
    if contenido is None:
        return
    carpeta.mkdir(parents=True, exist_ok=True)
    if isinstance(contenido, bytes):
        (carpeta / nombre).write_bytes(contenido)
    else:
        (carpeta / nombre).write_text(contenido, encoding="utf-8")


def _cerrar(salida: Path, resultados: list[dict]) -> int:
    (salida / "resumen.json").write_text(
        json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\nResumen:")
    for resultado in resultados:
        detalle = f"{resultado.get('codigo') or ''} {resultado.get('mensaje') or ''}"
        print(f"  {resultado['escenario']}: {resultado['estado']} {detalle}".rstrip())
    print(f"Todo quedó en {salida}")
    return 0 if all(r["estado"] in APPROVED for r in resultados) else 1


# --- Ejecucion ----------------------------------------------------------------


@dataclass
class Sesion:
    """Lo que comparten todos los envíos de una corrida."""

    config: dict
    emisor: Emitter
    timbrado: Stamping
    motor: KilaSifenEmissionEngine
    consultas: KilaSifenQueryGateway
    eventos: KilaSifenEventGateway
    credenciales: dict
    salida: Path


def _dry_run(config: dict, *, salida: Path, primero: int) -> int:
    emisor = _emisor(config)
    timbrado = _timbrado(config, emisor)
    mapper = KilaSifenPayloadMapper(
        test_emitter_name_literal=config["emisor"]["literal_ambiente_test"]
    )
    ok = True
    escenarios = _escenarios(config) + _escenarios_ronda2(config, cdc_factura="0" * 44)
    for desplazamiento, escenario in enumerate(escenarios):
        numero = primero + desplazamiento
        print(f"\n[{escenario.clave}] {escenario.titulo} (número {numero:07d})")
        try:
            documento = _documento(
                escenario, config=config, emisor=emisor, numero=numero
            )
            armado = mapper.map_document(
                documento,
                emitter=emisor,
                stamping=timbrado,
                signed_at=to_paraguay_wall_time(paraguay_now()),
            )
        except Exception as exc:
            ok = False
            print(f"  NO SE PUEDE ARMAR: {type(exc).__name__}: {exc}")
            continue
        print(f"  CDC {armado.doc_id}: XML válido contra el XSD")
        _imprimir_resumen_xml(_resumen_xml(armado.generated_xml))
        _guardar(salida / escenario.clave, "de_sin_firma.xml", armado.generated_xml)
    print(f"\nXML sin firmar en {salida}")
    return 0 if ok else 1


def _abrir_sesion(
    config: dict, *, p12: Path, salida: Path, sin_preguntar: bool
) -> Sesion:
    emisor = _emisor(config)
    pfx = p12.read_bytes()
    clave = _clave_de_windows(CREDENCIAL_WINDOWS)
    if clave is None:
        if not sys.stdin.isatty():
            raise SystemExit(
                f"No está la credencial de Windows {CREDENCIAL_WINDOWS}: guardala con "
                f"cmdkey /generic:{CREDENCIAL_WINDOWS} /user:sifen-test /pass"
            )
        clave = getpass.getpass("Contraseña del certificado (no se muestra): ")
    else:
        print(f"Contraseña tomada de la credencial de Windows {CREDENCIAL_WINDOWS}.")
    _revisar_certificado(pfx, clave, emisor.ruc, sin_preguntar=sin_preguntar)
    return Sesion(
        config=config,
        emisor=emisor,
        timbrado=_timbrado(config, emisor),
        motor=KilaSifenEmissionEngine(
            mapper=KilaSifenPayloadMapper(
                test_emitter_name_literal=config["emisor"]["literal_ambiente_test"]
            ),
            deployment_environment="test",
        ),
        consultas=KilaSifenQueryGateway(deployment_environment="test"),
        eventos=KilaSifenEventGateway(deployment_environment="test"),
        credenciales={"certificate_bytes": pfx, "certificate_password": clave},
        salida=salida,
    )


def _consultar_ruc(sesion: Sesion) -> bool:
    emisor = sesion.emisor
    print(f"\nConsulta RUC {emisor.ruc} en {TEST_HOST}...")
    try:
        ruc = _con_reintentos(
            lambda: sesion.consultas.query_ruc(
                emitter=emisor, ruc=emisor.ruc, **sesion.credenciales
            )
        )
    except Exception as exc:
        print(f"  FALLÓ la comunicación: {type(exc).__name__}: {exc}")
        return False
    _guardar(sesion.salida / "consulta_ruc", "respuesta.xml", ruc.response_raw)
    print(f"  {ruc.result_code} {ruc.result_message}")
    print(
        f"  razón social: {ruc.taxpayer_legal_name}; estado: {ruc.taxpayer_state}; "
        f"facturador electrónico: {ruc.electronic_taxpayer}"
    )
    return True


def _mostrar_emisor(sesion: Sesion) -> None:
    config = sesion.config
    perfil = config["emisor"]["perfil_fiscal"]
    domicilio = perfil["domicilio"]
    actividad = perfil["actividades_economicas"][0]
    print("\nDatos del emisor que viajan (tienen que coincidir con Marangatu):")
    print(f"  dNomEmi: {config['emisor']['literal_ambiente_test']}")
    print(
        f"  domicilio: {domicilio['direccion']} {domicilio['numero_casa']}, "
        f"{domicilio['descripcion_ciudad']}; tel. {domicilio['telefono']}; "
        f"{domicilio['email']}"
    )
    print(f"  actividad: {actividad['codigo']} {actividad['descripcion']}")
    print(
        f"  timbrado {sesion.timbrado.number} desde "
        f"{config['timbrado']['inicio_vigencia']}; CSC de prueba IdCSC "
        f"{config['csc']['id']}"
    )


def _ronda1(sesion: Sesion, numeracion: Numeracion, *, sin_preguntar: bool) -> int:
    escenarios = _escenarios(sesion.config)
    datos_timbrado = sesion.config["timbrado"]
    _mostrar_emisor(sesion)
    print(
        f"\nSe van a enviar {len(escenarios)} facturas al SIFEN de TEST "
        f"({TEST_HOST}), timbrado {sesion.timbrado.number}, "
        f"{datos_timbrado['establecimiento']}-{datos_timbrado['punto']}, "
        f"desde el número {numeracion.proximo:07d}:"
    )
    for escenario in escenarios:
        print(f"  - {escenario.titulo}")
    if not _confirmar("Escribí si para enviarlas: ", sin_preguntar=sin_preguntar):
        print("No se envió nada.")
        return 1
    resultados = [
        _enviar_escenario(escenario, sesion=sesion, numero=numeracion.reservar())
        for escenario in escenarios
    ]
    return _cerrar(sesion.salida, resultados)


def _ronda2(
    sesion: Sesion,
    numeracion: Numeracion,
    *,
    ronda1: Path,
    sin_preguntar: bool,
) -> int:
    anteriores = {
        r["escenario"]: r
        for r in json.loads((ronda1 / "resumen.json").read_text(encoding="utf-8"))
    }
    factura = anteriores.get("F1_b2b_iva10_iva5", {})
    a_cancelar = anteriores.get("F2_b2c_innominado_centavos", {})
    if (
        factura.get("estado") not in APPROVED
        or a_cancelar.get("estado") not in APPROVED
    ):
        raise SystemExit("La ronda 2 necesita F1 y F2 aprobadas en la ronda 1.")
    escenarios = _escenarios_ronda2(sesion.config, cdc_factura=factura["cdc"])
    _mostrar_emisor(sesion)
    print(
        f"\nRonda 2 en el SIFEN de TEST ({TEST_HOST}):"
        f"\n  - {escenarios[0].titulo}"
        f"\n  - {escenarios[1].titulo}"
        f"\n  - Cancelación de F2 ({a_cancelar['cdc']})"
        "\n  - Inutilización de dos números de factura del 001-001"
    )
    if not _confirmar("Escribí si para enviarla: ", sin_preguntar=sin_preguntar):
        print("No se envió nada.")
        return 1

    resultados = [
        _enviar_escenario(escenario, sesion=sesion, numero=numeracion.reservar())
        for escenario in escenarios
    ]
    cdc = a_cancelar["cdc"]
    resultado = _enviar_evento(
        "EV1_cancelacion_F2",
        f"Cancelación de F2 ({cdc})",
        CANCEL_EVENT_TYPE,
        lambda: build_signed_cancel_event_group_xml(
            cdc=cdc,
            motivo="Prueba de cancelacion en el ambiente de test",
            signed_at=paraguay_now(),
            event_id=_id_evento(),
            **sesion.credenciales,
        ),
        sesion=sesion,
    )
    if resultado["estado"] in APPROVED:
        verificacion = {"cdc": cdc}
        _consultar(verificacion, sesion, sesion.salida / "EV1_cancelacion_F2")
        resultado["consulta_cdc"] = verificacion.get("consulta")
    resultados.append(resultado)

    desde, hasta = numeracion.reservar(), numeracion.reservar()
    datos_timbrado = sesion.config["timbrado"]
    resultados.append(
        _enviar_evento(
            "EV2_inutilizacion",
            f"Inutilización de las facturas {desde:07d} a {hasta:07d}",
            INUTILIZATION_EVENT_TYPE,
            lambda: build_signed_inutilization_event_group_xml(
                timbrado=sesion.timbrado.number,
                i_tide=1,
                establishment=datos_timbrado["establecimiento"],
                point=datos_timbrado["punto"],
                numero_desde=desde,
                numero_hasta=hasta,
                motivo="Prueba de inutilizacion en el ambiente de test",
                signed_at=paraguay_now(),
                event_id=_id_evento(),
                **sesion.credenciales,
            ),
            sesion=sesion,
        )
    )
    return _cerrar(sesion.salida, resultados)


def _id_evento() -> str:
    """Id numérico corto del rEve, como ``EventService``."""

    return str(uuid4().int % 10_000_000_000) or "1"


def _enviar_evento(
    clave: str, titulo: str, tipo_evento: str, construir, *, sesion: Sesion
) -> dict:
    print(f"\n[{clave}] {titulo}")
    carpeta = sesion.salida / clave
    resultado: dict = {"escenario": clave}
    try:
        ahora = datetime.now(timezone.utc)
        evento = Event(
            id=f"sifen-test-{clave}",
            emitter_id=sesion.emisor.id,
            document_id=None,
            event_type=tipo_evento,
            input_payload={"event_xml": construir()},
            generated_xml=None,
            signed_xml=None,
            sifen_request_xml=None,
            sifen_response_raw=None,
            status="queued",
            sifen_result_code=None,
            sifen_result_message=None,
            created_at=ahora,
            updated_at=ahora,
        )
        preparado = sesion.eventos.prepare_event(
            event=evento, emitter=sesion.emisor, **sesion.credenciales
        )
    except Exception as exc:
        print(f"  NO SE ARMÓ (no se envió): {type(exc).__name__}: {exc}")
        return {**resultado, "estado": "no_armado", "mensaje": str(exc)}
    _guardar(carpeta, "evento_firmado.xml", preparado.signed_xml)
    _guardar(carpeta, "rEnviEventoDe.xml", preparado.request_xml)
    try:
        respuesta = sesion.eventos.submit_prepared(
            request_xml=preparado.request_xml,
            emitter=sesion.emisor,
            **sesion.credenciales,
        )
    except SifenRequestNotSentError as exc:
        print(f"  NO SE ENVIÓ (falló antes de salir): {exc}")
        return {**resultado, "estado": "no_enviado", "mensaje": str(exc)}
    except Exception as exc:
        # Un evento tiene efecto fiscal: nunca se reenvía a ciegas.
        print(f"  RESULTADO INCIERTO (no se reenvía): {type(exc).__name__}: {exc}")
        return {**resultado, "estado": "incierto", "mensaje": str(exc)}
    _guardar(carpeta, "respuesta.xml", respuesta.response_raw)
    resultado.update(
        estado=respuesta.status,
        codigo=respuesta.result_code,
        mensaje=respuesta.result_message,
        protocolo=respuesta.protocol,
    )
    print(
        f"  SIFEN: {respuesta.status} {respuesta.result_code} "
        f"{respuesta.result_message} (protocolo {respuesta.protocol or '-'})"
    )
    return resultado


def _enviar_escenario(escenario: Escenario, *, sesion: Sesion, numero: int) -> dict:
    print(f"\n[{escenario.clave}] {escenario.titulo} (número {numero:07d})")
    carpeta = sesion.salida / escenario.clave
    motor = sesion.motor
    resultado: dict = {"escenario": escenario.clave, "numero": numero}
    try:
        documento = _documento(
            escenario, config=sesion.config, emisor=sesion.emisor, numero=numero
        )
        preparado = motor.prepare_document(
            document=documento,
            emitter=sesion.emisor,
            stamping=sesion.timbrado,
            **sesion.credenciales,
        )
    except Exception as exc:
        print(f"  NO SE ARMÓ (no se envió): {type(exc).__name__}: {exc}")
        return {**resultado, "estado": "no_armado", "mensaje": str(exc)}
    resultado["cdc"] = preparado.cdc
    resultado["xml"] = _resumen_xml(preparado.signed_xml)
    _guardar(carpeta, "de_sin_firma.xml", preparado.generated_xml)
    _guardar(carpeta, "de_firmado.xml", preparado.signed_xml)
    _guardar(carpeta, "rEnviDe.xml", preparado.request_xml)
    print(f"  CDC {preparado.cdc}")
    _imprimir_resumen_xml(resultado["xml"])

    pedido = preparado.request_xml
    for intento in range(1, INTENTOS + 1):
        try:
            respuesta = motor.submit_prepared(
                request_xml=pedido, emitter=sesion.emisor, **sesion.credenciales
            )
        except SifenRequestNotSentError as exc:
            print(f"  NO SE ENVIÓ (falló antes de salir): {exc}")
            return {**resultado, "estado": "no_enviado", "mensaje": str(exc)}
        except Exception as exc:
            # Pudo haber llegado: nunca se reenvía, sólo se consulta el CDC.
            print(f"  RESULTADO INCIERTO: {type(exc).__name__}: {exc}")
            print("  No se reenvía. Consultando el CDC...")
            resultado.update(estado="incierto", mensaje=str(exc))
            _consultar(resultado, sesion, carpeta)
            return resultado
        codigos = [mensaje.code for mensaje in respuesta.messages]
        if codigos != ["0160"] or intento == INTENTOS:
            break
        # 0160 suelto puede ser la intermitencia del ambiente de pruebas. El
        # mismo rDE firmado sólo vuelve a viajar si el SIFEN no lo tiene
        # (0420), en un rEnviDe nuevo (regla 6 de CLAUDE.md).
        print(f"  0160 en el intento {intento}; se consulta el CDC antes de reenviar")
        time.sleep(PAUSA_SEGUNDOS)
        _consultar(resultado, sesion, carpeta)
        if resultado.get("consulta", {}).get("codigo") != "0420":
            break
        pedido = motor.wrap_signed_document(signed_xml=preparado.signed_xml)
        print("  El SIFEN no lo tiene (0420): se reenvía el mismo rDE firmado.")
    resultado["intentos"] = intento

    _guardar(carpeta, "respuesta.xml", respuesta.response_raw)
    resultado.update(
        estado=respuesta.sifen_status,
        codigo=respuesta.result_code,
        mensaje=respuesta.result_message,
        protocolo=respuesta.protocol,
        mensajes=[{"codigo": m.code, "mensaje": m.message} for m in respuesta.messages],
    )
    print(f"  SIFEN: {respuesta.sifen_status} (protocolo {respuesta.protocol or '-'})")
    for mensaje in respuesta.messages:
        print(f"    {mensaje.code}: {mensaje.message}")

    if respuesta.sifen_status in APPROVED:
        _consultar(resultado, sesion, carpeta)
        aprobado = replace(
            documento,
            signed_xml=preparado.signed_xml,
            cdc=preparado.cdc,
            internal_status="approved",
            sifen_status=respuesta.sifen_status,
        )
        try:
            kude = render_kude_pdf(document=aprobado, emitter=sesion.emisor)
        except Exception as exc:
            print(f"  KuDE no generado: {type(exc).__name__}: {exc}")
        else:
            _guardar(carpeta, "kude.pdf", kude)
            print("  KuDE: kude.pdf")
    return resultado


def _consultar(resultado: dict, sesion: Sesion, carpeta: Path) -> None:
    try:
        consulta = _con_reintentos(
            lambda: sesion.consultas.query_document(
                emitter=sesion.emisor, cdc=resultado["cdc"], **sesion.credenciales
            )
        )
    except Exception as exc:
        print(f"  Consulta por CDC falló: {type(exc).__name__}: {exc}")
        resultado["consulta"] = {"error": str(exc)}
        return
    _guardar(carpeta, "consulta_cdc.xml", consulta.response_raw)
    resultado["consulta"] = {
        "codigo": consulta.result_code,
        "mensaje": consulta.result_message,
        "estado": consulta.status,
        "cancelado": consulta.cancelled,
    }
    cancelado = " (con la cancelación registrada)" if consulta.cancelled else ""
    print(
        f"  Consulta por CDC: {consulta.result_code} {consulta.result_message}"
        f"{cancelado}"
    )


def _con_reintentos(consulta):
    """Repite una consulta (sin efecto fiscal) ante la intermitencia del ambiente."""

    for intento in range(1, INTENTOS + 1):
        try:
            return consulta()
        except SifenTransportError as exc:
            codigo = getattr(exc, "code", None)
            if intento == INTENTOS or codigo not in (None, "0160"):
                raise
            print(f"  intento {intento}: {codigo or type(exc).__name__}; se repite")
            time.sleep(PAUSA_SEGUNDOS)
    raise AssertionError("inalcanzable")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--p12", type=Path, help="Certificado del emisor (.p12/.pfx).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sólo arma y valida los XML: sin certificado y sin red.",
    )
    parser.add_argument(
        "--solo-ruc",
        action="store_true",
        help="Sólo prueba la comunicación con una consulta RUC.",
    )
    parser.add_argument(
        "--ronda2",
        type=Path,
        help="Carpeta de una ronda 1 con F1 y F2 aprobadas: NC, ND y eventos.",
    )
    parser.add_argument(
        "--si",
        action="store_true",
        help="No pide confirmación antes de enviar (siempre a TEST).",
    )
    parser.add_argument(
        "--primer-numero",
        type=int,
        help="dNumDoc del primer envío (por defecto, el guardado en estado.json).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = _parse_args(argv)
    trabajo = args.config.resolve().parent
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    salida = trabajo / ("dry-run" if args.dry_run else "runs") / marca
    _instalar_candados(trafico=salida / "http")
    print(f"AMBIENTE: TEST ({TEST_HOST}). Producción bloqueada en este proceso.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    numeracion = Numeracion(
        trabajo / "estado.json", primero=config["numeracion"]["primer_numero"]
    )
    if args.primer_numero is not None:
        numeracion.proximo = args.primer_numero
    if args.dry_run:
        return _dry_run(config, salida=salida, primero=numeracion.proximo)
    if args.p12 is None:
        raise SystemExit("Falta --p12 con la ruta del certificado.")
    sesion = _abrir_sesion(config, p12=args.p12, salida=salida, sin_preguntar=args.si)
    if not _consultar_ruc(sesion):
        return 3
    if args.solo_ruc:
        print(f"Todo quedó en {salida}")
        return 0
    if args.ronda2 is not None:
        return _ronda2(sesion, numeracion, ronda1=args.ronda2, sin_preguntar=args.si)
    return _ronda1(sesion, numeracion, sin_preguntar=args.si)


if __name__ == "__main__":
    raise SystemExit(main())
