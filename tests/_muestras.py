"""Registro compartido de las muestras XML v150 y de sus valores declarados.

Las muestras de ``kilasifen/engine/de/samples/v150`` son documentos ficticios
escritos para las pruebas. Este modulo es la unica fuente de los valores que
los tests comparan contra ellas: ningun test debe repetir literales de una
muestra; los toma de aqui (``MUESTRAS`` o las constantes por documento).

Datos ficticios:

- todas las muestras las emite la misma persona juridica inventada
  (``Lapacho Sur Comercial S.A.``) con un unico timbrado;
- los RUC (emisor, receptores y transportista) son inventados, cumplen el
  patron ``tRuc`` de v150 y llevan el DV correcto por modulo 11; no coinciden
  con ningun RUC presente en el repositorio;
- el CDC de cada documento es el que devuelve
  ``kilasifen.engine.sdk.fiscal.generate_cdc`` con los campos del propio
  documento, y ``dDVId`` es su ultimo digito;
- la ``Signature`` es de relleno: ``DigestValue`` y ``SignatureValue`` son
  base64 canonico de bytes derivados con SHA-256 de un texto fijo, no una
  firma real (el firmador los reemplaza);
- ``dCarQR`` se genero con ``generate_dcarqr_from_signed_xml`` (base de
  produccion) sobre la propia muestra: los literales del XML, el
  ``DigestValue`` de relleno, ``ID_CSC`` y el CSC ficticio ``CSC``.

Cobertura de tipos: solo los tipos ACTIVOS en ``DE_Types_v150.xsd`` (patron
``1|[4-7]|9|10``) que el binding ``fe_v141`` puede representar. Ver
``TIPOS_SIN_MUESTRA`` para los que quedan fuera y el motivo.

Limitaciones del binding ``fe_v141`` (layout FE v1.41) que condicionan las
muestras:

- ninguna puede llevar elementos exclusivos de v150 (``dSisFact``,
  ``gValorRestaItem``, ``dBasExe``...): el parser los rechaza. La validez v150
  se comprueba sobre una copia normalizada (procedimiento P-V150 en
  ``tests/test_de.py``);
- ``gTimb/dFeFinT`` sigue presente porque v141 lo exige;
- la constancia de la autofactura va en ``gCamAE`` (layout v141). En v150
  viajaria en ``gCamDEAsoc`` con ``iTipDocAso`` 3, que el binding no conoce.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

DIR_MUESTRAS = (
    Path(__file__).resolve().parents[1]
    / "kilasifen"
    / "engine"
    / "de"
    / "samples"
    / "v150"
)

#: Tipos de DE con muestra (vigentes en v150 y legibles con ``fe_v141``).
TIPOS_ACTIVOS_V150 = frozenset({"1", "4", "5", "6", "7"})

#: Tipos sin muestra y por que.
TIPOS_SIN_MUESTRA: Mapping[str, str] = MappingProxyType(
    {
        "2": "factura de exportacion: comentada en DE_Types_v150.xsd",
        "3": "factura de importacion: comentada en DE_Types_v150.xsd",
        "8": "comprobante de retencion: comentado en DE_Types_v150.xsd",
        "9": (
            "boleta de venta: vigente en v150, sin muestra todavia; el binding "
            "fe_v141 restringe iTiDE a 1|[5-6] (4 y 7 tambien quedan fuera y "
            "se leen con ConverterWarning) y no hay datos de referencia"
        ),
        "10": (
            "boleta resimple: vigente en v150, sin muestra todavia; el binding "
            "fe_v141 restringe iTiDE a 1|[5-6] (4 y 7 tambien quedan fuera y "
            "se leen con ConverterWarning) y no hay datos de referencia"
        ),
    }
)

#: Identificador y CSC ficticios usados para generar los ``dCarQR``.
ID_CSC = "0001"
CSC = "KilaSifenMuestraCscFicticio2026A"

#: Campo que xsdata no puede convertir al leer los tipos 4 y 7: la enumeracion
#: ``TdDesTiDe`` del binding solo conoce las descripciones de los tipos 1, 5 y 6.
ADVERTENCIA_DESCRIPCION_TIPO = "TgDtim.dDesTiDE"


@dataclass(frozen=True)
class ItemMuestra:
    """Valores declarados de un ``gCamItem``.

    Los montos son ``None`` cuando el item no los lleva (nota de remision) y
    los de IVA, cuando el item no tiene ``gCamIVA`` (autofactura).
    """

    codigo: str
    descripcion: str
    unidad: int
    cantidad: Decimal
    precio_unitario: Decimal | None = None
    total: Decimal | None = None
    base_gravada: Decimal | None = None
    iva: Decimal | None = None
    tasa_iva: int | None = None


@dataclass(frozen=True)
class Muestra:
    """Valores declarados de un archivo de muestra.

    Los campos opcionales valen ``None`` cuando el grupo no existe en ese tipo
    de documento (por ejemplo, ``gTotSub`` en la nota de remision).
    """

    archivo: str
    tipo: str
    descripcion_tipo: str
    cdc: str
    dv_id: str
    fecha_firma: str
    fecha_emision: str
    codigo_seguridad: str
    timbrado: str
    inicio_timbrado: str
    fin_timbrado: str
    establecimiento: str
    punto_expedicion: str
    numero_documento: str
    ruc_emisor: str
    dv_emisor: str
    tipo_contribuyente_emisor: str
    nombre_emisor: str
    direccion_emisor: str
    email_emisor: str
    ruc_receptor: str
    dv_receptor: str
    nombre_receptor: str
    items: tuple[ItemMuestra, ...]
    digest_relleno: str
    firma_relleno: str
    id_csc: str = ID_CSC
    csc: str = CSC
    subtotal_10: Decimal | None = None
    base_gravada_10: Decimal | None = None
    iva_10: Decimal | None = None
    total_iva: Decimal | None = None
    total_general: Decimal | None = None
    monto_pago: Decimal | None = None
    motivo: str | None = None
    descripcion_motivo: str | None = None
    cdc_asociado: str | None = None
    nombre_vendedor: str | None = None
    id_vendedor: str | None = None
    motivo_traslado: int | None = None
    ruc_transportista: str | None = None
    dv_transportista: str | None = None
    advertencias_admitidas: frozenset[str] = frozenset()

    @property
    def ruta(self) -> Path:
        """Ruta absoluta del archivo de la muestra."""
        return DIR_MUESTRAS / self.archivo

    @property
    def cantidad_items(self) -> int:
        """Cantidad de ``gCamItem`` del documento."""
        return len(self.items)

    @property
    def codigos_items(self) -> tuple[str, ...]:
        """Codigos internos (``dCodInt``) de los items, en orden."""
        return tuple(item.codigo for item in self.items)

    @property
    def cantidad_primer_item(self) -> Decimal:
        """``dCantProSer`` del primer item."""
        return self.items[0].cantidad

    @property
    def precio_unitario_primer_item(self) -> Decimal | None:
        """``dPUniProSer`` del primer item (``None`` si no lleva valores)."""
        return self.items[0].precio_unitario


# ---------------------------------------------------------------------------
# Datos ficticios compartidos
# ---------------------------------------------------------------------------

#: Emisor de todas las muestras (persona juridica, RUC 80172649-2).
_EMISOR = {
    "ruc_emisor": "80172649",
    "dv_emisor": "2",
    "tipo_contribuyente_emisor": "2",
    "nombre_emisor": "Lapacho Sur Comercial S.A.",
    "direccion_emisor": "Calle Yvyrá Pytã esquina Los Lapachos",
    "email_emisor": "facturacion@lapachosur.example",
}

#: Timbrado unico del emisor.
_TIMBRADO = {
    "timbrado": "16482039",
    "inicio_timbrado": "2025-11-03",
    "fin_timbrado": "2026-12-31",
}

#: Cliente de la factura y de las notas de credito y debito.
_CLIENTE_VIVERO = {
    "ruc_receptor": "80293518",
    "dv_receptor": "4",
    "nombre_receptor": "Viveros Tres Arroyos S.R.L.",
}

_MANGUERA = "Manguera de riego reforzada de 25 m"


# ---------------------------------------------------------------------------
# Muestras
# ---------------------------------------------------------------------------

FACTURA = Muestra(
    archivo="factura_electronica.xml",
    tipo="1",
    descripcion_tipo="Factura electrónica",
    cdc="01801726492001001000014822026031214829130767",
    dv_id="7",
    fecha_firma="2026-03-12T10:24:31",
    fecha_emision="2026-03-12T10:24:05",
    codigo_seguridad="482913076",
    establecimiento="001",
    punto_expedicion="001",
    numero_documento="0000148",
    **_TIMBRADO,
    **_EMISOR,
    **_CLIENTE_VIVERO,
    items=(
        ItemMuestra(
            codigo="LS-1042",
            descripcion=_MANGUERA,
            unidad=77,
            cantidad=Decimal("3"),
            precio_unitario=Decimal("185000"),
            total=Decimal("555000"),
            base_gravada=Decimal("504545"),
            iva=Decimal("50455"),
            tasa_iva=10,
        ),
        ItemMuestra(
            codigo="LS-2210",
            descripcion="Servicio de instalación de riego por goteo",
            unidad=77,
            cantidad=Decimal("1"),
            precio_unitario=Decimal("340000"),
            total=Decimal("340000"),
            base_gravada=Decimal("309091"),
            iva=Decimal("30909"),
            tasa_iva=10,
        ),
    ),
    subtotal_10=Decimal("895000"),
    base_gravada_10=Decimal("813636"),
    iva_10=Decimal("81364"),
    total_iva=Decimal("81364"),
    total_general=Decimal("895000"),
    monto_pago=Decimal("895000"),
    digest_relleno="uIVzH5wQQFum96Ws81f23mp2PsxWrSX6Alado4d/dsQ=",
    firma_relleno=(
        "E+fdeMYAryVehOuJuTQ8YgZ6lB/SkCKTyaqAIypi2NHKpbQ1O+YAKchGiM7UCs/Q"
        "/0MbQxAvh+7ngDMOVJC08E0QLXnhJ3GgaeCIn3xwk6r9e2PHaAfIDheJGSQu2irn"
        "SzsUdcRUB7YS4qNqNfZH/ChH/3nGbnpskYaJidMHpNSjGJ5rRKeNbrRpKHSg8/1a"
        "/LUSmXv9fZ33n89f7z7SmdEmXUMg8aQMj89TYc1poZsEGMKxBrQ3vKFQt3FuBeqB"
        "wH95VHErRQl26WY3+XWCpm0gegLH0tfzm9WOUnXuaSTmDF/GH2U9XListwQLsAl6"
        "w4aEaKbwCsfbAmpkPrahmA=="
    ),
)

AUTOFACTURA = Muestra(
    archivo="autofactura.xml",
    tipo="4",
    descripcion_tipo="Autofactura electrónica",
    cdc="04801726492001002000004122026031616402918538",
    dv_id="8",
    fecha_firma="2026-03-16T08:47:40",
    fecha_emision="2026-03-16T08:47:12",
    codigo_seguridad="640291853",
    establecimiento="001",
    punto_expedicion="002",
    numero_documento="0000041",
    **_TIMBRADO,
    **_EMISOR,
    # En la autofactura el receptor es el propio emisor (comprador).
    ruc_receptor=_EMISOR["ruc_emisor"],
    dv_receptor=_EMISOR["dv_emisor"],
    nombre_receptor=_EMISOR["nombre_emisor"],
    items=(
        ItemMuestra(
            codigo="LS-AF01",
            descripcion="Miel de abeja pura, frasco de 1 kg",
            unidad=77,
            cantidad=Decimal("12"),
            precio_unitario=Decimal("38000"),
            total=Decimal("456000"),
        ),
        ItemMuestra(
            codigo="LS-AF02",
            descripcion="Cera de abeja en bloque",
            unidad=83,
            cantidad=Decimal("4.5"),
            precio_unitario=Decimal("26000"),
            total=Decimal("117000"),
        ),
    ),
    total_general=Decimal("573000"),
    monto_pago=Decimal("573000"),
    nombre_vendedor="Rosalía Benítez Ozuna",
    id_vendedor="3816402",
    advertencias_admitidas=frozenset({ADVERTENCIA_DESCRIPCION_TIPO}),
    digest_relleno="1PVanlHkrJYlafFNwguHJyLOJT0xKBwWKOiOH0YU0Fw=",
    firma_relleno=(
        "pxImkY9THXEcKnj2p7GC0VvwSnSlOYUezuRCvGlT4KZrmkH8cKtF/eOY/hIme9s5"
        "TJg6fgbavWk6YKgcwx63P87H94ObNuZi5bJh9q0yqta5z+3ZKbN0Iz/purrXLOCg"
        "qrZnZQAplEmEC02WRCQ5iHd2uYpQEssyYgXVLD7LUzHYxXGp8uc1D5+Aq6/Bz+Rh"
        "aJh4BdfzUhvKlXjA/wVy1Sd0q+hKQOMCuHJZSytcZ0q3i+5KosD8/5cupWBonj4u"
        "ZY7CXzH9AfGmLB4C1evuJsRsYUMMFnZsI3JaMc34GonkmgpPpBy8v3AkpKM1qQC0"
        "C9DvKmeArykf4R/b8dpwCA=="
    ),
)

NOTA_CREDITO = Muestra(
    archivo="nota_credito.xml",
    tipo="5",
    descripcion_tipo="Nota de crédito electrónica",
    cdc="05801726492001001000002322026032013057182645",
    dv_id="5",
    fecha_firma="2026-03-20T15:03:10",
    fecha_emision="2026-03-20T15:02:44",
    codigo_seguridad="305718264",
    establecimiento="001",
    punto_expedicion="001",
    numero_documento="0000023",
    **_TIMBRADO,
    **_EMISOR,
    **_CLIENTE_VIVERO,
    items=(
        ItemMuestra(
            codigo="LS-1042",
            descripcion=_MANGUERA,
            unidad=77,
            cantidad=Decimal("1"),
            precio_unitario=Decimal("185000"),
            total=Decimal("185000"),
            base_gravada=Decimal("168182"),
            iva=Decimal("16818"),
            tasa_iva=10,
        ),
    ),
    subtotal_10=Decimal("185000"),
    base_gravada_10=Decimal("168182"),
    iva_10=Decimal("16818"),
    total_iva=Decimal("16818"),
    total_general=Decimal("185000"),
    motivo="2",
    descripcion_motivo="Devolución",
    # Devolucion parcial de la factura de muestra.
    cdc_asociado=FACTURA.cdc,
    digest_relleno="hMOXHa2pAuYeQTf/xqbCUU7BUa41KypSgkxVIghjGh8=",
    firma_relleno=(
        "BpdLLiU+Tu6lLytZyEe7sihcSm2nq47CeWvmfq4HPDopsDfi3tuZ01Tnamtgnqif"
        "1qp3EQnKM1sZsEP7uUnwHuD53BigdZPpx20XXbbTN41IUq/tILYteVMAlXDHmLH3"
        "Q8svUJ9YcQSKlUa5Yn4754fVnCWo/8Ac8yAvC4WqF5AtHPh/uugG+gHLu27nuYdz"
        "1bkpZcSPhUInuQPHcskoAKzmhmcwbRzDJ3ro1D9viGOBtkT9KWbft1psdBuCNPZJ"
        "xo+Zi1ZQnbkTZPbFRnHUg+TsGvpc5d+uXc/76CB7fXgc8gynHnnA3r+bK2OzPY9X"
        "NxeyEffitEt+ykOeAegCUw=="
    ),
)

NOTA_DEBITO = Muestra(
    archivo="nota_debito.xml",
    tipo="6",
    descripcion_tipo="Nota de débito electrónica",
    cdc="06801726492001001000000922026032419173645205",
    dv_id="5",
    fecha_firma="2026-03-24T11:30:52",
    fecha_emision="2026-03-24T11:30:18",
    codigo_seguridad="917364520",
    establecimiento="001",
    punto_expedicion="001",
    numero_documento="0000009",
    **_TIMBRADO,
    **_EMISOR,
    **_CLIENTE_VIVERO,
    items=(
        ItemMuestra(
            codigo="LS-FL01",
            descripcion="Recupero de gasto de flete no incluido en la factura",
            unidad=77,
            cantidad=Decimal("1"),
            precio_unitario=Decimal("60000"),
            total=Decimal("60000"),
            base_gravada=Decimal("54545"),
            iva=Decimal("5455"),
            tasa_iva=10,
        ),
    ),
    subtotal_10=Decimal("60000"),
    base_gravada_10=Decimal("54545"),
    iva_10=Decimal("5455"),
    total_iva=Decimal("5455"),
    total_general=Decimal("60000"),
    motivo="7",
    descripcion_motivo="Recupero de gasto",
    cdc_asociado=FACTURA.cdc,
    digest_relleno="FXIVslaplSUhybD+nkbj/Xc5Ql/XiI48b8YjTa5xicU=",
    firma_relleno=(
        "q+JIeDdVSQaRgoceBXtHRLCOM4MGNdDE0quXaGWxO7+6jFsBvabhZYa6eL5xhzGU"
        "VaA+yQVHOMpLKQHLRU/vnUV7z4SHJSSeOrZtH4lJ6CDbRY5iRnRwdxBHH7t8OhUM"
        "fuuj9RTx93iT3QUbAPyCtoRpnmGIRSH/8uRy9qQuCKXwNHUlf1Qh9E7wyNwBQnbA"
        "Vp0KhXchFopyQhw2Sl8CDw9oLYwirx9FO2hHOxWUx7Bj9en0PUZv/g446TaGyBeD"
        "XuGhCB4wGYhtSEKANQip9rTumzyE7gbTxUYWjTW3E8wasC92Lu6iTw1SBdojDQIF"
        "IzE3d+3JsYHp3Y5oesZc8Q=="
    ),
)

NOTA_REMISION = Muestra(
    archivo="nota_remision.xml",
    tipo="7",
    descripcion_tipo="Nota de remisión electrónica",
    cdc="07801726492001003000031522026032712584061976",
    dv_id="6",
    fecha_firma="2026-03-27T07:55:41",
    fecha_emision="2026-03-27T07:55:09",
    codigo_seguridad="258406197",
    establecimiento="001",
    punto_expedicion="003",
    numero_documento="0000315",
    **_TIMBRADO,
    **_EMISOR,
    ruc_receptor="80415736",
    dv_receptor="7",
    nombre_receptor="Jardines Mburucuyá S.A.",
    items=(
        ItemMuestra(
            codigo="LS-3307",
            descripcion="Sustrato orgánico para macetas, bolsa de 50 L",
            unidad=77,
            cantidad=Decimal("40"),
        ),
        ItemMuestra(
            codigo="LS-3412",
            descripcion="Fertilizante granulado NPK 15-15-15",
            unidad=83,
            cantidad=Decimal("250"),
        ),
    ),
    motivo_traslado=1,
    descripcion_motivo="Traslado por ventas",
    ruc_transportista="80538427",
    dv_transportista="8",
    advertencias_admitidas=frozenset({ADVERTENCIA_DESCRIPCION_TIPO}),
    digest_relleno="R73M5fHINEsViEuuKQv2aSs/hlniH2moiLAmFrwn1dk=",
    firma_relleno=(
        "io5hipqm1hgPjmjqqY+grwIbJ852N6djMJ/1EtWDFlWkKVGucPteU+pdXbjVnF2o"
        "7nyoPMDjx1ihD0BhX2EO1Ry9pCmigHZBVROzCpsNrWZBX/OXwOjnZQckISiYlalg"
        "GXUYRuRUP30nWbZnp26s5klg7u3/CVgS3NAx5sn6vCpCiDFBYmhOoeYCVm41nFUb"
        "Bb4/pWdCyxCwZEznBDVaeRjPOrFDOnYvj3rURcIdGKUQYytRGWL91U6pmNkBB6jn"
        "d7vCsiTqOWHIWxiNlDdItUt6IEG2Af+K+ddcWHRZqo6EYIbrXjaMNvPZG59zkcVR"
        "7nraL7pdQXQdFvs+01JtlA=="
    ),
)

#: Registro inmutable indexado por nombre de archivo.
MUESTRAS: Mapping[str, Muestra] = MappingProxyType(
    {
        muestra.archivo: muestra
        for muestra in (
            FACTURA,
            AUTOFACTURA,
            NOTA_CREDITO,
            NOTA_DEBITO,
            NOTA_REMISION,
        )
    }
)

#: Nombres de archivo de todas las muestras, en orden alfabetico.
ARCHIVOS_MUESTRAS: tuple[str, ...] = tuple(sorted(MUESTRAS))
