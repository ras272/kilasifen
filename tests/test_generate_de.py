"""Construccion programatica, serializacion y firma de DE con los bindings v150.

El modulo ejercita de punta a punta las dataclasses generadas de ``fe_v141``:

- construccion de documentos electronicos por tipo (factura al contado y a
  credito, notas de credito y de debito, nota de remision) y su lectura
  despues de serializarlos;
- ida y vuelta (serializar, reparsear y volver a serializar) de documentos
  construidos y de cada muestra del registro ``tests/_muestras.py``;
- lectura profunda de las muestras contra los valores que declara el registro;
- estructura del XML que produce ``to_xml`` y compilacion de los XSD raiz
  desde su ubicacion en disco;
- firma XMLDSig de una muestra con el certificado efimero de
  ``tests/conftest.py`` y disponibilidad de ``sign_xml`` en las clases.

Los documentos construidos usan datos ficticios propios de este modulo y no
pretenden validar contra el XSD v150 (el binding modela el layout FE v1.41 y
la firma es de relleno): cada test verifica solo lo que construyo. Los
valores esperados de las muestras salen siempre del registro.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from lxml import etree

from kilasifen.engine.binding import BindingMixin
from kilasifen.engine.de.bindings.v150.fe_v141 import (
    CMondT,
    PaisType,
    RDe,
    TcUniMed,
    TDe,
    TDepartamentos,
    TDesDepartamento,
    TgActEco,
    TgCamCond,
    TgCamDeasoc,
    TgCamFe,
    TgCamFuFd,
    TgCamItem,
    TgCamIva,
    TgCamNcde,
    TgCamNre,
    TgCopeDe,
    TgCuotas,
    TgDaGoc,
    TgDatRec,
    TgDtim,
    TgDtipDe,
    TgEmis,
    TgOpeCom,
    TgPagCont,
    TgPagCred,
    TgPagCredICondCred,
    TgTotSub,
    TgValorItem,
    TiAfecIva,
    TiCondOpe,
    TiIndPres,
    TiMotEmi,
    TiMotivTras,
    TiRespEmiNr,
    TiTimp,
    TiTiPago,
    TiTipDocAso,
    TiTipTra,
)
from kilasifen.engine.de.bindings.v150.xmldsig_core_schema import (
    CanonicalizationMethod,
    DigestMethod,
    DigestValue,
    Reference,
    Signature,
    SignatureMethod,
    SignatureValue,
    SignedInfo,
)
from kilasifen.engine.sdk.fiscal import generate_cdc
from tests._muestras import (
    ARCHIVOS_MUESTRAS,
    AUTOFACTURA,
    DIR_MUESTRAS,
    FACTURA,
    MUESTRAS,
    NOTA_CREDITO,
    NOTA_REMISION,
    Muestra,
)

# Al reparsear, xsdata emite ConverterWarning cuando una descripcion no
# coincide con la enumeracion del binding (por ejemplo ``dDesTiDE`` de la nota
# de remision). El texto se conserva y la ida y vuelta sigue siendo estable.
pytestmark = pytest.mark.filterwarnings(
    "ignore::xsdata.exceptions.ConverterWarning"
)

DIR_ESQUEMAS = (
    Path(__file__).resolve().parents[1]
    / "kilasifen"
    / "engine"
    / "de"
    / "schemas"
    / "v150"
)

#: XSD raiz que deben compilar desde disco (todos sus includes son locales).
ESQUEMAS_RAIZ = (
    "FE_v141.xsd",
    "DE_v150.xsd",
    "Evento_v150.xsd",
    "siRecepDE_v150.xsd",
)

NS_SIFEN = "http://ekuatia.set.gov.py/sifen/xsd"
NS_XMLDSIG = "http://www.w3.org/2000/09/xmldsig#"
DECLARACION_XML = '<?xml version="1.0" encoding="UTF-8"?>'

#: PKCS#12 efimero que ``tests/conftest.py`` escribe al iniciar la sesion.
CERTIFICADO_PRUEBA = Path(__file__).with_name("test_cert.pfx")
CLAVE_CERTIFICADO = "test1234"

# Algoritmos W3C de la firma de relleno.
C14N_10 = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

# Codigos de catalogo SIFEN de los documentos construidos.
VERSION_FORMATO = "150"
TIPO_EMISION_NORMAL = "1"
TIPO_FACTURA = "1"
TIPO_NOTA_CREDITO = "5"
TIPO_NOTA_DEBITO = "6"
TIPO_NOTA_REMISION = "7"
DESCRIPCION_TIPO_DE = {
    TIPO_FACTURA: "Factura electrónica",
    TIPO_NOTA_CREDITO: "Nota de crédito electrónica",
    TIPO_NOTA_DEBITO: "Nota de débito electrónica",
    TIPO_NOTA_REMISION: "Nota de remisión electrónica",
}
TASA_IVA_GENERAL = 10
QR_PROVISORIO = "https://ekuatia.set.gov.py/consultas/qr?nVersion=150"

# Datos ficticios de los documentos construidos (no salen de ninguna muestra).
RUC_EMISOR = "80361574"
DV_EMISOR = "4"
TIPO_CONTRIBUYENTE_EMISOR = "2"
RAZON_SOCIAL_EMISOR = "Ferretería Arroyo Porã S.A."
TIMBRADO = "17293846"
INICIO_TIMBRADO = "2026-01-15"
FIN_TIMBRADO = "2027-01-14"
ESTABLECIMIENTO = "001"
FECHA_EMISION = "2026-05-18T09:42:17"
FECHA_FIRMA = "2026-05-18T09:42:51"
CODIGO_SEGURIDAD = "573910284"

TODAS_LAS_MUESTRAS = [MUESTRAS[archivo] for archivo in ARCHIVOS_MUESTRAS]

#: Parametriza un test sobre exactamente el conjunto de muestras del registro.
por_muestra = pytest.mark.parametrize(
    "muestra", TODAS_LAS_MUESTRAS, ids=list(ARCHIVOS_MUESTRAS)
)


# ---------------------------------------------------------------------------
# Fabricas de documentos
# ---------------------------------------------------------------------------


def _firma_provisoria() -> Signature:
    """``Signature`` de relleno para el campo obligatorio ``RDe.Signature``.

    Tiene la forma de una firma RSA-SHA256 con C14N 1.0 y una unica
    referencia (URI vacia, digest SHA-256), pero el digest y el valor son
    bytes en cero: no es una firma real.
    """
    return Signature(
        SignedInfo=SignedInfo(
            CanonicalizationMethod=CanonicalizationMethod(Algorithm=C14N_10),
            SignatureMethod=SignatureMethod(Algorithm=RSA_SHA256),
            Reference=[
                Reference(
                    URI="",
                    DigestMethod=DigestMethod(Algorithm=SHA256),
                    DigestValue=DigestValue(value=bytes(32)),
                )
            ],
        ),
        SignatureValue=SignatureValue(value=bytes(256)),
    )


def _emisor_prueba() -> TgEmis:
    """Emisor ficticio: persona juridica con domicilio en Asuncion."""
    return TgEmis(
        dRucEm=RUC_EMISOR,
        dDVEmi=DV_EMISOR,
        iTipCont=TIPO_CONTRIBUYENTE_EMISOR,
        dNomEmi=RAZON_SOCIAL_EMISOR,
        dDirEmi="Calle Ñandutí Poty casi Arroyo Porã",
        dNumCas=1450,
        cDepEmi=TDepartamentos.VALUE_1,
        dDesDepEmi=TDesDepartamento.CAPITAL,
        cDisEmi="1",
        dDesDisEmi="ASUNCION (DISTRITO)",
        cCiuEmi="1",
        dDesCiuEmi="ASUNCION (DISTRITO)",
        dTelEmi="021555014",
        dEmailE="ventas@arroyopora.example",
        gActEco=[
            TgActEco(
                cActEco="47520",
                dDesActEco="Comercio al por menor de artículos de ferretería",
            )
        ],
    )


def _receptor_prueba() -> TgDatRec:
    """Receptor ficticio: contribuyente paraguayo, persona fisica con RUC."""
    return TgDatRec(
        iNatRec="1",
        iTiOpe="1",
        cPaisRec=PaisType.PRY,
        dDesPaisRe="Paraguay",
        iTiContRec="1",
        dRucRec="3527861",
        dDVRec="7",
        dNomRec="Marcelino Cáceres Duarte",
        dDirRec="Calle Los Timbós 318",
    )


def _base_gravada(total: Decimal) -> Decimal:
    """Base imponible de un monto con IVA incluido, redondeada a guaranies."""
    divisor = 1 + Decimal(TASA_IVA_GENERAL) / 100
    return (total / divisor).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _item_prueba(
    codigo: str,
    descripcion: str,
    cantidad: int | Decimal,
    precio_unitario: int | Decimal,
) -> TgCamItem:
    """Item por unidades, sin descuento y gravado al 10 % con IVA incluido."""
    cantidad = Decimal(cantidad)
    precio_unitario = Decimal(precio_unitario)
    total = cantidad * precio_unitario
    base = _base_gravada(total)
    return TgCamItem(
        dCodInt=codigo,
        dDesProSer=descripcion,
        cUniMed=TcUniMed.VALUE_77,
        dDesUniMed="UNI",
        dCantProSer=cantidad,
        gValorItem=TgValorItem(
            dPUniProSer=precio_unitario,
            dDescItem=Decimal(0),
            dTotOpeItem=total,
            dTotOpeGs=total,
        ),
        gCamIVA=TgCamIva(
            iAfecIVA=TiAfecIva.VALUE_1,
            dDesAfecIVA="Gravado IVA",
            dPropIVA=100,
            dTasaIVA=TASA_IVA_GENERAL,
            dBasGravIVA=base,
            dLiqIVAItem=total - base,
        ),
    )


def _total_items(items: Sequence[TgCamItem]) -> Decimal:
    """Suma de los totales de linea."""
    return sum((item.gValorItem.dTotOpeItem for item in items), Decimal(0))


def _totales_prueba(items: Sequence[TgCamItem]) -> TgTotSub:
    """``gTotSub`` coherente con los items: sin descuentos ni anticipos."""
    total = _total_items(items)
    base = sum((item.gCamIVA.dBasGravIVA for item in items), Decimal(0))
    iva = sum((item.gCamIVA.dLiqIVAItem for item in items), Decimal(0))
    cero = Decimal(0)
    return TgTotSub(
        dSub10=total,
        dTotOpe=total,
        dTotDesc=cero,
        dPorcDescTotal=cero,
        dDescTotal=cero,
        dAnticipo=cero,
        dRedon=cero,
        dTotGralOpe=total,
        dIVA10=iva,
        dTotIVA=iva,
        dBaseGrav10=base,
        dTBasGraIVA=base,
        dTotalGs=total,
    )


def _operacion_comercial() -> TgOpeCom:
    """Venta de mercaderias en guaranies, gravada con IVA."""
    return TgOpeCom(
        iTipTra=TiTipTra.VALUE_1,
        dDesTipTra="Venta de mercadería",
        iTImp=TiTimp.VALUE_1,
        dDesTImp="IVA",
        cMoneOpe=CMondT.PYG,
        dDesMoneOpe="Guarani",
    )


def _contado(monto: Decimal) -> TgCamCond:
    """Condicion contado con un unico pago en efectivo por ``monto``."""
    return TgCamCond(
        iCondOpe=TiCondOpe.VALUE_1,
        dDCondOpe="Contado",
        gPaConEIni=[
            TgPagCont(
                iTiPago=TiTiPago.VALUE_1,
                dDesTiPag="Efectivo",
                dMonTiPag=monto,
                cMoneTiPag=CMondT.PYG,
                dDMoneTiPag="Guarani",
            )
        ],
    )


def _credito_en_cuotas(cuotas: Sequence[tuple[Decimal, str]]) -> TgCamCond:
    """Condicion credito pagadera en ``cuotas`` (monto, vencimiento)."""
    return TgCamCond(
        iCondOpe=TiCondOpe.VALUE_2,
        dDCondOpe="Crédito",
        gPagCred=TgPagCred(
            iCondCred=TgPagCredICondCred.VALUE_2,
            dDCondCred="Cuota",
            dCuotas=len(cuotas),
            dMonEnt=Decimal(0),
            gCuotas=[
                TgCuotas(dMonCuota=monto, dVencCuo=vencimiento)
                for monto, vencimiento in cuotas
            ],
        ),
    )


def _presencial() -> TgCamFe:
    """Grupo de factura: operacion presencial."""
    return TgCamFe(iIndPres=TiIndPres.VALUE_1, dDesIndPres="Operación presencial")


def _cdc(tipo: str, numero_documento: str, punto_expedicion: str) -> str:
    """CDC de 44 digitos de un documento ficticio de ``RUC_EMISOR``."""
    return generate_cdc(
        i_tide=tipo,
        d_ruc_em=RUC_EMISOR,
        d_dv_emi=DV_EMISOR,
        d_est=ESTABLECIMIENTO,
        d_pun_exp=punto_expedicion,
        d_num_doc=numero_documento,
        i_tip_cont=TIPO_CONTRIBUYENTE_EMISOR,
        d_fe_emi_de=FECHA_EMISION,
        i_tip_emi=TIPO_EMISION_NORMAL,
        d_cod_seg=CODIGO_SEGURIDAD,
    )


def _asociado_electronico(cdc: str) -> TgCamDeasoc:
    """Referencia a un DE electronico anterior por su CDC."""
    return TgCamDeasoc(
        iTipDocAso=TiTipDocAso.VALUE_1,
        dDesTipDocAso="Electrónico",
        dCdCDERef=cdc,
    )


def _construir_rde(
    tipo: str,
    numero_documento: str,
    items: Sequence[TgCamItem],
    *,
    condicion: TgCamCond | None = None,
    con_operacion_comercial: bool = True,
    asociados: Sequence[TgCamDeasoc] = (),
    punto_expedicion: str = "001",
    **grupos_del_tipo: object,
) -> RDe:
    """Arma un ``rDE`` completo con la cabecera comun de los DE construidos.

    ``grupos_del_tipo`` son los grupos especificos de ``gDtipDE`` (por
    ejemplo ``gCamFE=_presencial()``). El CDC se calcula con los propios
    campos del documento y ``dDVId`` es su ultimo digito.
    """
    cdc = _cdc(tipo, numero_documento, punto_expedicion)
    return RDe(
        dVerFor=VERSION_FORMATO,
        DE=TDe(
            Id=cdc,
            dDVId=cdc[-1],
            dFecFirma=FECHA_FIRMA,
            gOpeDE=TgCopeDe(
                iTipEmi=TIPO_EMISION_NORMAL,
                dDesTipEmi="Normal",
                dCodSeg=CODIGO_SEGURIDAD,
            ),
            gTimb=TgDtim(
                iTiDE=tipo,
                dDesTiDE=DESCRIPCION_TIPO_DE[tipo],
                dNumTim=TIMBRADO,
                dEst=ESTABLECIMIENTO,
                dPunExp=punto_expedicion,
                dNumDoc=numero_documento,
                dFeIniT=INICIO_TIMBRADO,
                dFeFinT=FIN_TIMBRADO,
            ),
            gDatGralOpe=TgDaGoc(
                dFeEmiDE=FECHA_EMISION,
                gOpeCom=_operacion_comercial() if con_operacion_comercial else None,
                gEmis=_emisor_prueba(),
                gDatRec=_receptor_prueba(),
            ),
            gDtipDE=TgDtipDe(
                gCamCond=condicion,
                gCamItem=list(items),
                **grupos_del_tipo,
            ),
            gTotSub=_totales_prueba(items),
            gCamDEAsoc=list(asociados),
        ),
        Signature=_firma_provisoria(),
        gCamFuFD=TgCamFuFd(dCarQR=QR_PROVISORIO),
    )


def _factura_contado(
    numero_documento: str,
    items: Sequence[TgCamItem],
    punto_expedicion: str = "001",
) -> RDe:
    """Factura presencial al contado, pagada en efectivo por el total."""
    return _construir_rde(
        TIPO_FACTURA,
        numero_documento,
        items,
        condicion=_contado(_total_items(items)),
        punto_expedicion=punto_expedicion,
        gCamFE=_presencial(),
    )


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _ida_y_vuelta(rde: RDe) -> tuple[str, RDe, str]:
    """Serializa, reparsea y vuelve a serializar, siempre con sangria."""
    primero = rde.to_xml()
    releido = RDe.from_xml(primero)
    return primero, releido, releido.to_xml()


def _contiene_elemento(xml: str, etiqueta: str, valor: str) -> bool:
    """Indica si ``xml`` tiene ``<etiqueta>valor</etiqueta>`` con cualquier prefijo."""
    prefijo = r"(?:[\w.-]+:)?"
    patron = (
        rf"<{prefijo}{etiqueta}>{re.escape(valor)}</{prefijo}{etiqueta}>"
    )
    return re.search(patron, xml) is not None


def cargar(muestra: Muestra) -> RDe:
    """Lee una muestra del registro con el binding ``fe_v141``."""
    return RDe.from_path(muestra.ruta)


@pytest.fixture
def ruta_certificado() -> Path:
    """Ruta del PKCS#12 efimero, junto a este modulo."""
    return CERTIFICADO_PRUEBA


@pytest.fixture
def datos_certificado(ruta_certificado: Path) -> bytes:
    """Bytes del PKCS#12, leidos al correr el test (``conftest`` lo crea antes)."""
    if not ruta_certificado.is_file():
        pytest.skip(f"no existe el certificado de prueba {ruta_certificado.name}")
    return ruta_certificado.read_bytes()


# ---------------------------------------------------------------------------
# Tema A: construccion programatica por tipo de DE
# ---------------------------------------------------------------------------


class TestConstruyeFactura:
    """Facturas electronicas armadas con las dataclasses del binding."""

    def test_factura_contado_un_item(self) -> None:
        cantidad, precio = 2, 385000
        item = _item_prueba("FRT-0107", "Taladro percutor de 800 W", cantidad, precio)
        rde = _factura_contado("0000201", [item])

        xml = rde.to_xml()

        assert xml.startswith(DECLARACION_XML)
        assert _contiene_elemento(xml, "dRucEm", RUC_EMISOR)
        assert _contiene_elemento(xml, "dNomEmi", RAZON_SOCIAL_EMISOR)
        assert _contiene_elemento(xml, "dCodInt", "FRT-0107")
        assert _contiene_elemento(xml, "dTotGralOpe", str(cantidad * precio))

    def test_factura_varios_items(self) -> None:
        lineas = (
            ("FRT-0311", "Llave inglesa ajustable de 12 pulgadas", 2, 96000),
            ("FRT-0312", "Juego de destornilladores de precisión", 3, 58500),
            ("FRT-0313", "Nivel de burbuja de aluminio de 60 cm", 1, 142000),
        )
        items = [_item_prueba(*linea) for linea in lineas]
        total = sum(cantidad * precio for _, _, cantidad, precio in lineas)
        rde = _factura_contado("0000202", items, punto_expedicion="002")

        _, releido, _ = _ida_y_vuelta(rde)

        items_releidos = releido.DE.gDtipDE.gCamItem
        assert len(items_releidos) == len(lineas)
        assert [item.dCodInt for item in items_releidos] == [
            codigo for codigo, *_ in lineas
        ]
        assert releido.DE.gTimb.dPunExp == "002"
        assert releido.DE.gTotSub.dTotGralOpe == Decimal(total)

    def test_factura_credito_en_cuotas(self) -> None:
        # La primera cuota absorbe el redondeo y difiere de las otras dos:
        # asi se detecta si el orden de las cuotas cambia.
        cuotas = (
            (Decimal("816668"), "2026-06-18"),
            (Decimal("816666"), "2026-07-18"),
            (Decimal("816666"), "2026-08-18"),
        )
        item = _item_prueba(
            "FRT-0920", "Compresor de aire de 50 litros", 1, 2450000
        )
        assert _total_items([item]) == sum(monto for monto, _ in cuotas)
        rde = _construir_rde(
            TIPO_FACTURA,
            "0000203",
            [item],
            condicion=_credito_en_cuotas(cuotas),
            gCamFE=_presencial(),
        )

        _, releido, _ = _ida_y_vuelta(rde)

        condicion = releido.DE.gDtipDE.gCamCond
        assert condicion.iCondOpe == TiCondOpe.VALUE_2
        assert condicion.gPaConEIni == []
        assert condicion.gPagCred is not None
        assert len(condicion.gPagCred.gCuotas) == len(cuotas)
        assert condicion.gPagCred.gCuotas[0].dMonCuota == cuotas[0][0]
        assert [cuota.dMonCuota for cuota in condicion.gPagCred.gCuotas] == [
            monto for monto, _ in cuotas
        ]


class TestConstruyeNotaCreditoDebito:
    """Notas de credito y de debito: comparten el grupo ``gCamNCDE``."""

    @pytest.mark.parametrize(
        ("tipo", "motivo", "descripcion_motivo", "linea"),
        [
            pytest.param(
                TIPO_NOTA_CREDITO,
                TiMotEmi.VALUE_1,
                "Devolución y Ajuste de precios",
                ("FRT-0107", "Devolución de taladro percutor de 800 W", 1, 385000),
                id="nota_credito",
            ),
            pytest.param(
                TIPO_NOTA_DEBITO,
                TiMotEmi.VALUE_7,
                "Recupero de gasto",
                ("GST-0004", "Recupero de gasto de envío a domicilio", 1, 45000),
                id="nota_debito",
            ),
        ],
    )
    def test_nota_credito_debito(
        self,
        tipo: str,
        motivo: TiMotEmi,
        descripcion_motivo: str,
        linea: tuple[str, str, int, int],
    ) -> None:
        _, _, cantidad, precio = linea
        cdc_factura = _cdc(TIPO_FACTURA, "0000201", "001")
        rde = _construir_rde(
            tipo,
            "0000031",
            [_item_prueba(*linea)],
            condicion=_contado(Decimal(cantidad * precio)),
            asociados=[_asociado_electronico(cdc_factura)],
            gCamNCDE=TgCamNcde(iMotEmi=motivo, dDesMotEmi=descripcion_motivo),
        )

        _, releido, _ = _ida_y_vuelta(rde)

        de = releido.DE
        assert de.gTimb.iTiDE == tipo
        assert de.gDtipDE.gCamNCDE is not None
        assert de.gDtipDE.gCamNCDE.iMotEmi == motivo
        assert len(de.gCamDEAsoc) == 1
        assert de.gCamDEAsoc[0].dCdCDERef == cdc_factura
        assert de.gTotSub.dTotGralOpe == Decimal(cantidad * precio)


class TestConstruyeNotaRemision:
    """Nota de remision: sin operacion comercial ni condicion de pago."""

    def test_nota_remision_con_motivo_traslado(self) -> None:
        cantidad, precio = 120, 18500
        rde = _construir_rde(
            TIPO_NOTA_REMISION,
            "0000057",
            [
                _item_prueba(
                    "FRT-1180",
                    "Caja de clavos de acero de 2 pulgadas",
                    cantidad,
                    precio,
                )
            ],
            con_operacion_comercial=False,
            gCamNRE=TgCamNre(
                iMotEmiNR=[TiMotivTras.VALUE_1],
                dDesMotEmiNR=["Traslado por ventas"],
                iRespEmiNR=TiRespEmiNr.VALUE_1,
            ),
        )

        _, releido, _ = _ida_y_vuelta(rde)

        de = releido.DE
        assert de.gTimb.iTiDE == TIPO_NOTA_REMISION
        assert de.gDatGralOpe.gOpeCom is None
        assert de.gDtipDE.gCamCond is None
        remision = de.gDtipDE.gCamNRE
        assert remision is not None
        assert remision.iMotEmiNR[0] == TiMotivTras.VALUE_1
        assert de.gTotSub.dTotGralOpe == Decimal(cantidad * precio)


# ---------------------------------------------------------------------------
# Tema B: ida y vuelta
# ---------------------------------------------------------------------------


class TestIdaYVuelta:
    """Serializar, reparsear y volver a serializar no cambia el documento."""

    def test_muestra_factura_conserva_campos(self) -> None:
        original = cargar(FACTURA)

        primero, releido, segundo = _ida_y_vuelta(original)

        for rde in (original, releido):
            de = rde.DE
            emisor = de.gDatGralOpe.gEmis
            assert (
                de.Id,
                de.gTimb.iTiDE,
                emisor.dRucEm,
                emisor.dNomEmi,
                de.gTotSub.dTotGralOpe,
            ) == (
                FACTURA.cdc,
                FACTURA.tipo,
                FACTURA.ruc_emisor,
                FACTURA.nombre_emisor,
                FACTURA.total_general,
            )
        assert primero == segundo
        assert releido == original

    @por_muestra
    def test_xml_estable_por_muestra(self, muestra: Muestra) -> None:
        primero, _, segundo = _ida_y_vuelta(cargar(muestra))
        assert primero == segundo, (
            f"{muestra.archivo}: la segunda serializacion difiere de la primera"
        )

    def test_muestras_del_directorio_son_las_del_registro(self) -> None:
        en_disco = sorted(
            ruta.name
            for ruta in DIR_MUESTRAS.iterdir()
            if ruta.is_file() and ruta.suffix == ".xml"
        )
        assert en_disco, f"no hay muestras .xml en {DIR_MUESTRAS}"
        assert tuple(en_disco) == ARCHIVOS_MUESTRAS

    def test_factura_generada_estable(self) -> None:
        cantidad, precio = 4, 127500
        item = _item_prueba(
            "FRT-0450", "Amoladora angular de 115 mm", cantidad, precio
        )
        rde = _factura_contado("0000204", [item])

        primero, releido, segundo = _ida_y_vuelta(rde)

        assert primero == segundo
        assert releido.DE.gDtipDE.gCamItem[0].dCodInt == "FRT-0450"
        total = releido.DE.gTotSub.dTotGralOpe
        assert isinstance(total, Decimal)
        assert total == Decimal(cantidad * precio)


# ---------------------------------------------------------------------------
# Tema C: lectura profunda de muestras
# ---------------------------------------------------------------------------


class TestLecturaMuestras:
    """Navegacion completa del arbol de cada muestra contra el registro."""

    def test_navega_factura(self) -> None:
        rde = cargar(FACTURA)
        assert rde.dVerFor == VERSION_FORMATO
        assert rde.Signature is not None
        assert rde.gCamFuFD is not None

        de = rde.DE
        assert de.Id is not None
        assert len(de.Id) == 44
        assert de.dDVId == FACTURA.dv_id
        assert de.dFecFirma is not None

        assert de.gOpeDE.iTipEmi == TIPO_EMISION_NORMAL
        assert de.gOpeDE.dCodSeg is not None

        timbrado = de.gTimb
        assert timbrado.iTiDE == FACTURA.tipo
        assert timbrado.dNumTim is not None
        assert timbrado.dEst == FACTURA.establecimiento
        assert timbrado.dPunExp == FACTURA.punto_expedicion

        general = de.gDatGralOpe
        assert general.dFeEmiDE is not None
        assert general.gOpeCom.cMoneOpe == CMondT.PYG

        emisor = general.gEmis
        assert (
            emisor.dRucEm,
            emisor.dDVEmi,
            emisor.iTipCont,
            emisor.dNomEmi,
        ) == (
            FACTURA.ruc_emisor,
            FACTURA.dv_emisor,
            FACTURA.tipo_contribuyente_emisor,
            FACTURA.nombre_emisor,
        )
        assert emisor.dDirEmi is not None
        assert emisor.cDepEmi is not None
        assert emisor.dEmailE is not None
        assert len(emisor.gActEco) >= 1

        receptor = general.gDatRec
        assert (receptor.dRucRec, receptor.dNomRec) == (
            FACTURA.ruc_receptor,
            FACTURA.nombre_receptor,
        )

        especificos = de.gDtipDE
        assert especificos.gCamFE is not None
        assert especificos.gCamCond is not None
        assert len(especificos.gCamItem) == FACTURA.cantidad_items

        item = especificos.gCamItem[0]
        esperado = FACTURA.items[0]
        assert (item.dCodInt, item.dDesProSer, item.dCantProSer) == (
            esperado.codigo,
            esperado.descripcion,
            FACTURA.cantidad_primer_item,
        )
        assert item.gValorItem is not None
        assert item.gValorItem.dPUniProSer == FACTURA.precio_unitario_primer_item
        assert item.gCamIVA is not None
        assert item.gCamIVA.dTasaIVA == esperado.tasa_iva

        assert de.gTotSub.dTotGralOpe == FACTURA.total_general

    def test_navega_nota_credito(self) -> None:
        de = cargar(NOTA_CREDITO).DE
        assert de.gTimb.iTiDE == NOTA_CREDITO.tipo
        assert de.gDtipDE.gCamNCDE is not None
        assert len(de.gCamDEAsoc) >= 1
        asociado = de.gCamDEAsoc[0]
        assert asociado.iTipDocAso == TiTipDocAso.VALUE_1
        assert asociado.dCdCDERef is not None
        assert len(asociado.dCdCDERef) == 44
        assert asociado.dCdCDERef == NOTA_CREDITO.cdc_asociado

    def test_navega_autofactura(self) -> None:
        # El nombre del vendedor lleva caracteres no ASCII: su lectura exacta
        # comprueba que la muestra se decodifica como UTF-8.
        assert not AUTOFACTURA.nombre_vendedor.isascii()
        de = cargar(AUTOFACTURA).DE
        assert de.gTimb.iTiDE == AUTOFACTURA.tipo
        vendedor = de.gDtipDE.gCamAE
        assert vendedor is not None
        assert vendedor.dNomVen == AUTOFACTURA.nombre_vendedor
        assert vendedor.dNumIDVen == AUTOFACTURA.id_vendedor
        assert vendedor.dDirVen is not None

    def test_navega_nota_remision(self) -> None:
        de = cargar(NOTA_REMISION).DE
        assert de.gTimb.iTiDE == NOTA_REMISION.tipo
        assert de.gDtipDE.gCamNRE is not None
        items = de.gDtipDE.gCamItem
        assert len(items) == NOTA_REMISION.cantidad_items
        assert items[0].dCodInt == NOTA_REMISION.items[0].codigo
        assert items[0].dCantProSer == NOTA_REMISION.cantidad_primer_item


# ---------------------------------------------------------------------------
# Tema D: estructura del XML y compilacion de esquemas
# ---------------------------------------------------------------------------


class TestEstructuraXml:
    """Forma del XML de ``to_xml`` y XSD que se pueden compilar localmente."""

    @por_muestra
    def test_inicia_con_declaracion_xml(self, muestra: Muestra) -> None:
        assert cargar(muestra).to_xml().startswith(DECLARACION_XML)

    @por_muestra
    def test_xml_bien_formado_por_muestra(self, muestra: Muestra) -> None:
        raiz = etree.fromstring(cargar(muestra).to_xml().encode("utf-8"))
        assert raiz.tag == f"{{{NS_SIFEN}}}rDE"

    @por_muestra
    def test_declara_namespace_sifen(self, muestra: Muestra) -> None:
        assert "ekuatia.set.gov.py/sifen/xsd" in cargar(muestra).to_xml()

    @por_muestra
    def test_declara_namespace_xmldsig(self, muestra: Muestra) -> None:
        assert "www.w3.org/2000/09/xmldsig" in cargar(muestra).to_xml()

    @pytest.mark.parametrize("nombre", ESQUEMAS_RAIZ)
    def test_esquema_xsd_compila(self, nombre: str) -> None:
        # Se parsea por ruta para que los schemaLocation relativos se
        # resuelvan contra el directorio del XSD; desde bytes sin URL base
        # los includes no se encuentran.
        parser = etree.XMLParser(no_network=True)
        documento = etree.parse(str(DIR_ESQUEMAS / nombre), parser)
        esquema = etree.XMLSchema(documento)
        assert esquema is not None


# ---------------------------------------------------------------------------
# Tema E: firma
# ---------------------------------------------------------------------------


class TestFirmaXml:
    """Firma XMLDSig a traves de ``BindingMixin.sign_xml``."""

    def test_firma_o_indica_extra_sign(self, datos_certificado: bytes) -> None:
        # Version estricta: con el extra de firma instalado, firmar debe
        # funcionar. Sin el extra se omite; el mensaje de ``ImportError`` que
        # pide ``kilasifen[sign]`` lo cubre ``tests/test_firma.py``.
        pytest.importorskip("signxml")
        pytest.importorskip("cryptography")
        rde = cargar(FACTURA)
        xml = rde.to_xml()

        firmado = rde.sign_xml(xml, datos_certificado, CLAVE_CERTIFICADO, rde.DE.Id)

        assert isinstance(firmado, str)
        raiz = etree.fromstring(firmado.encode("utf-8"))
        firmas = raiz.findall(f".//{{{NS_XMLDSIG}}}Signature")
        assert len(firmas) == 1, "la firma de relleno debe reemplazarse"
        referencias = firmas[0].findall(f".//{{{NS_XMLDSIG}}}Reference")
        assert [referencia.get("URI") for referencia in referencias] == [
            f"#{rde.DE.Id}"
        ]
        digest = referencias[0].findtext(f"{{{NS_XMLDSIG}}}DigestValue")
        valor = firmas[0].findtext(f"{{{NS_XMLDSIG}}}SignatureValue")
        assert "".join(digest.split()) != FACTURA.digest_relleno
        assert "".join(valor.split()) != FACTURA.firma_relleno
        assert FACTURA.digest_relleno not in firmado
        assert FACTURA.firma_relleno not in firmado

    @pytest.mark.parametrize("clase", [RDe, TDe, TgEmis], ids=lambda c: c.__name__)
    def test_sign_xml_disponible(self, clase: type) -> None:
        assert callable(getattr(clase, "sign_xml", None))
        assert issubclass(clase, BindingMixin)

    def test_certificado_prueba_es_pkcs12(self, datos_certificado: bytes) -> None:
        pkcs12 = pytest.importorskip(
            "cryptography.hazmat.primitives.serialization.pkcs12"
        )
        clave, certificado, _ = pkcs12.load_key_and_certificates(
            datos_certificado, CLAVE_CERTIFICADO.encode()
        )
        assert clave is not None
        assert certificado is not None
        assert certificado.subject.rfc4514_string()
