"""Lectura, navegacion, serializacion e ida y vuelta de las muestras v150.

Las muestras viven en ``kilasifen/engine/de/samples/v150`` y se leen con el
binding ``fe_v141`` (el unico ``RDe`` generado; modela el layout FE v1.41).
Todos los valores esperados salen del registro compartido
``tests/_muestras.py``: aqui no se repiten literales de las muestras.

Ademas de leer y serializar, el modulo comprueba la coherencia interna de cada
muestra (CDC, digitos verificadores, montos, QR, firma de relleno y formato
del archivo) y su validez contra ``siRecepDE_v150.xsd`` despues de
normalizarla a v150 (procedimiento P-V150, ver ``_normalizar_a_v150``).
"""

from __future__ import annotations

import base64
import re
import warnings
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from lxml import etree
from xsdata.exceptions import ConverterWarning

from kilasifen.engine.de.bindings.v150.fe_v141 import (
    RDe,
    TgEmis,
    TiAfecIva,
    TiCondOpe,
    TiMotEmi,
    TiMotivTras,
)
from kilasifen.engine.sdk.fiscal import (
    calculate_mod11_dv,
    generate_cdc,
    generate_dcarqr,
    generate_dcarqr_from_signed_xml,
)
from kilasifen.engine.sdk.validation import validate_xml
from tests._muestras import (
    ARCHIVOS_MUESTRAS,
    AUTOFACTURA,
    FACTURA,
    MUESTRAS,
    NOTA_CREDITO,
    NOTA_DEBITO,
    NOTA_REMISION,
    TIPOS_ACTIVOS_V150,
    Muestra,
)

# Los tipos 4 y 7 emiten un ConverterWarning legitimo al leerse (ver
# ``Muestra.advertencias_admitidas``); el test dedicado lo vuelve a capturar.
pytestmark = pytest.mark.filterwarnings(
    "ignore::xsdata.exceptions.ConverterWarning"
)

SAMPLES_DIR = (
    Path(__file__).resolve().parents[1]
    / "kilasifen"
    / "engine"
    / "de"
    / "samples"
    / "v150"
)

NS_SIFEN = "http://ekuatia.set.gov.py/sifen/xsd"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
DECLARACION_XML = '<?xml version="1.0" encoding="UTF-8"?>'
PREFIJO_QR_PRODUCCION = "https://ekuatia.set.gov.py/consultas/qr?"

#: PKCS#12 efimero que ``tests/conftest.py`` escribe en cada sesion de pytest.
CERTIFICADO_PRUEBA = Path(__file__).with_name("test_cert.pfx")
CLAVE_CERTIFICADO_PRUEBA = "test1234"

TODAS = [MUESTRAS[archivo] for archivo in ARCHIVOS_MUESTRAS]
CON_TOTALES = [muestra for muestra in TODAS if muestra.total_general is not None]

por_muestra = pytest.mark.parametrize(
    "muestra", TODAS, ids=[muestra.archivo for muestra in TODAS]
)
por_muestra_con_totales = pytest.mark.parametrize(
    "muestra", CON_TOTALES, ids=[muestra.archivo for muestra in CON_TOTALES]
)


def cargar(muestra: Muestra) -> RDe:
    """Lee una muestra con el binding ``fe_v141``."""
    return RDe.from_path(SAMPLES_DIR / muestra.archivo)


def _valor(campo: object) -> object:
    """Devuelve el ``value`` de un enum del binding, o el dato tal cual."""
    return getattr(campo, "value", campo)


def _o_none(monto: Decimal) -> Decimal | None:
    """Un subtotal que suma cero no aparece en el XML."""
    return monto if monto else None


# ---------------------------------------------------------------------------
# Lectura de cada tipo
# ---------------------------------------------------------------------------


class TestLecturaFactura:
    """Navegacion por la factura electronica de muestra (tipo 1)."""

    def test_lee_factura_con_version_150(self) -> None:
        rde = cargar(FACTURA)
        assert rde is not None
        assert rde.dVerFor == "150"

    def test_factura_es_tipo_1(self) -> None:
        assert FACTURA.tipo == "1"
        assert cargar(FACTURA).DE.gTimb.iTiDE == FACTURA.tipo

    def test_factura_datos_del_emisor(self) -> None:
        emisor = cargar(FACTURA).DE.gDatGralOpe.gEmis
        assert emisor.dRucEm == FACTURA.ruc_emisor
        assert emisor.dNomEmi == FACTURA.nombre_emisor
        assert emisor.dDirEmi == FACTURA.direccion_emisor
        assert emisor.dEmailE == FACTURA.email_emisor

    def test_factura_datos_del_receptor(self) -> None:
        receptor = cargar(FACTURA).DE.gDatGralOpe.gDatRec
        assert receptor.dRucRec == FACTURA.ruc_receptor
        assert receptor.dNomRec == FACTURA.nombre_receptor

    def test_factura_detalle_de_items(self) -> None:
        items = cargar(FACTURA).DE.gDtipDE.gCamItem
        primero, segundo = FACTURA.items
        assert len(items) == FACTURA.cantidad_items == 2
        assert items[0].dCodInt == primero.codigo
        assert items[0].dDesProSer == primero.descripcion
        assert items[1].dCodInt == segundo.codigo

    def test_factura_totales(self) -> None:
        totales = cargar(FACTURA).DE.gTotSub
        assert isinstance(totales.dTotGralOpe, Decimal)
        assert totales.dTotGralOpe == FACTURA.total_general
        assert totales.dSub10 == FACTURA.subtotal_10
        assert totales.dIVA10 == FACTURA.iva_10

    def test_factura_iva_del_primer_item(self) -> None:
        iva = cargar(FACTURA).DE.gDtipDE.gCamItem[0].gCamIVA
        assert iva.iAfecIVA == TiAfecIva.VALUE_1
        assert iva.dTasaIVA == FACTURA.items[0].tasa_iva == 10

    def test_factura_condicion_contado(self) -> None:
        condicion = cargar(FACTURA).DE.gDtipDE.gCamCond
        assert condicion.iCondOpe == TiCondOpe.VALUE_1
        assert len(condicion.gPaConEIni) == 1
        assert condicion.gPaConEIni[0].dMonTiPag == FACTURA.monto_pago

    def test_factura_campos_fuera_de_firma(self) -> None:
        rde = cargar(FACTURA)
        assert rde.gCamFuFD is not None
        assert "ekuatia.set.gov.py" in rde.gCamFuFD.dCarQR


class TestLecturaNotaCredito:
    """Nota de credito electronica de muestra (tipo 5)."""

    def test_nota_credito_es_tipo_5(self) -> None:
        assert NOTA_CREDITO.tipo == "5"
        assert cargar(NOTA_CREDITO).DE.gTimb.iTiDE == NOTA_CREDITO.tipo

    def test_nota_credito_motivo_de_emision(self) -> None:
        ncde = cargar(NOTA_CREDITO).DE.gDtipDE.gCamNCDE
        assert ncde is not None
        assert ncde.iMotEmi == TiMotEmi(NOTA_CREDITO.motivo)

    def test_nota_credito_tiene_documento_asociado(self) -> None:
        asociados = cargar(NOTA_CREDITO).DE.gCamDEAsoc
        assert asociados is not None
        assert len(asociados) > 0
        assert asociados[0].iTipDocAso.value == 1
        assert asociados[0].dCdCDERef == NOTA_CREDITO.cdc_asociado


class TestLecturaAutofactura:
    """Autofactura electronica de muestra (tipo 4)."""

    def test_autofactura_es_tipo_4(self) -> None:
        assert AUTOFACTURA.tipo == "4"
        assert cargar(AUTOFACTURA).DE.gTimb.iTiDE == AUTOFACTURA.tipo

    def test_autofactura_datos_del_vendedor(self) -> None:
        autofactura = cargar(AUTOFACTURA).DE.gDtipDE.gCamAE
        assert autofactura is not None
        assert autofactura.dNomVen == AUTOFACTURA.nombre_vendedor
        assert autofactura.dNumIDVen == AUTOFACTURA.id_vendedor


class TestLecturaNotaRemision:
    """Nota de remision electronica de muestra (tipo 7)."""

    def test_nota_remision_es_tipo_7(self) -> None:
        assert NOTA_REMISION.tipo == "7"
        assert cargar(NOTA_REMISION).DE.gTimb.iTiDE == NOTA_REMISION.tipo

    def test_nota_remision_motivo_de_traslado(self) -> None:
        remision = cargar(NOTA_REMISION).DE.gDtipDE.gCamNRE
        assert remision is not None
        assert isinstance(remision.iMotEmiNR, list)
        assert len(remision.iMotEmiNR) == 1
        motivo = remision.iMotEmiNR[0]
        assert isinstance(motivo, TiMotivTras)
        assert motivo.value == NOTA_REMISION.motivo_traslado


class TestLecturaNotaDebito:
    """Nota de debito electronica de muestra (tipo 6)."""

    def test_nota_debito_es_tipo_6(self) -> None:
        assert NOTA_DEBITO.tipo == "6"
        assert cargar(NOTA_DEBITO).DE.gTimb.iTiDE == NOTA_DEBITO.tipo

    def test_nota_debito_motivo_de_emision(self) -> None:
        ncde = cargar(NOTA_DEBITO).DE.gDtipDE.gCamNCDE
        assert ncde is not None
        assert ncde.iMotEmi == TiMotEmi(NOTA_DEBITO.motivo)


class TestLecturaDesdeTexto:
    """Lectura desde un texto XML en memoria."""

    def test_from_xml_acepta_texto(self) -> None:
        texto = (SAMPLES_DIR / FACTURA.archivo).read_text(encoding="utf-8")
        rde = RDe.from_xml(texto)
        assert rde.DE.gDatGralOpe.gEmis.dRucEm == FACTURA.ruc_emisor


# ---------------------------------------------------------------------------
# Serializacion
# ---------------------------------------------------------------------------


class TestSerializacion:
    """Serializacion con ``to_xml`` y lectura de vuelta."""

    def test_to_xml_incluye_declaracion_y_datos(self) -> None:
        xml = cargar(FACTURA).to_xml()
        assert DECLARACION_XML in xml
        assert FACTURA.ruc_emisor in xml
        assert FACTURA.nombre_emisor in xml

    def test_ida_y_vuelta_conserva_campos_clave(self) -> None:
        original = cargar(FACTURA)
        releido = RDe.from_xml(original.to_xml())
        emisor_original = original.DE.gDatGralOpe.gEmis
        emisor_releido = releido.DE.gDatGralOpe.gEmis
        assert releido.dVerFor == original.dVerFor
        assert releido.DE.Id == original.DE.Id
        assert emisor_releido.dRucEm == emisor_original.dRucEm
        assert emisor_releido.dNomEmi == emisor_original.dNomEmi
        assert len(releido.DE.gDtipDE.gCamItem) == len(
            original.DE.gDtipDE.gCamItem
        )
        assert releido.DE.gTotSub.dTotGralOpe == original.DE.gTotSub.dTotGralOpe

    @por_muestra
    def test_ida_y_vuelta_conserva_id_en_todas_las_muestras(
        self, muestra: Muestra
    ) -> None:
        original = cargar(muestra)
        releido = RDe.from_xml(original.to_xml())
        assert releido.DE.Id == original.DE.Id, (
            f"{muestra.archivo}: el Id del DE cambio en la ida y vuelta"
        )

    def test_muestras_cubren_los_tipos_activos_v150(self) -> None:
        tipos = {str(cargar(muestra).DE.gTimb.iTiDE) for muestra in TODAS}
        assert tipos == TIPOS_ACTIVOS_V150

    def test_to_xml_compacto_es_mas_corto(self) -> None:
        rde = cargar(FACTURA)
        assert len(rde.to_xml(pretty_print=False)) < len(
            rde.to_xml(pretty_print=True)
        )


class TestMixinDeBindings:
    """Las clases generadas exponen los metodos de ``BindingMixin``."""

    def test_rde_expone_metodos_del_mixin(self) -> None:
        for nombre in ("from_xml", "from_path", "to_xml", "validate_xml", "sign_xml"):
            assert callable(getattr(RDe, nombre, None)), nombre

    def test_subclases_exponen_metodos_del_mixin(self) -> None:
        for nombre in ("from_xml", "to_xml"):
            assert callable(getattr(TgEmis, nombre, None)), nombre


# ---------------------------------------------------------------------------
# Coherencia de las muestras con el registro y entre sus propios campos
# ---------------------------------------------------------------------------

_GRUPOS_DTIP = (
    "gCamFE",
    "gCamFEE",
    "gCamFEI",
    "gCamAE",
    "gCamNCDE",
    "gCamNRE",
    "gCamCond",
    "gCamEsp",
    "gTransp",
)

#: Grupos de ``gDtipDE`` presentes en cada tipo (tabla de requisitos por tipo).
_GRUPOS_POR_TIPO = {
    "1": frozenset({"gCamFE", "gCamCond"}),
    "4": frozenset({"gCamAE", "gCamCond"}),
    "5": frozenset({"gCamNCDE"}),
    "6": frozenset({"gCamNCDE"}),
    "7": frozenset({"gCamNRE", "gTransp"}),
}

_MOTIVOS_POR_TIPO = {
    "5": frozenset({"2", "3", "4", "5"}),
    "6": frozenset({"6", "7", "8"}),
}

_CAMPO_ADVERTENCIA = re.compile(r"`(\w+\.\w+)`")


class TestCoherenciaMuestras:
    """Cada muestra coincide con el registro y es coherente consigo misma."""

    @por_muestra
    def test_registro_identificacion(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        timbrado = de.gTimb
        assert (de.Id, de.dDVId, de.dFecFirma, de.gOpeDE.dCodSeg) == (
            muestra.cdc,
            muestra.dv_id,
            muestra.fecha_firma,
            muestra.codigo_seguridad,
        )
        assert (timbrado.iTiDE, _valor(timbrado.dDesTiDE)) == (
            muestra.tipo,
            muestra.descripcion_tipo,
        )
        assert (
            timbrado.dNumTim,
            timbrado.dFeIniT,
            timbrado.dFeFinT,
            timbrado.dEst,
            timbrado.dPunExp,
            timbrado.dNumDoc,
        ) == (
            muestra.timbrado,
            muestra.inicio_timbrado,
            muestra.fin_timbrado,
            muestra.establecimiento,
            muestra.punto_expedicion,
            muestra.numero_documento,
        )
        assert de.gDatGralOpe.dFeEmiDE == muestra.fecha_emision

    @por_muestra
    def test_registro_emisor_y_receptor(self, muestra: Muestra) -> None:
        general = cargar(muestra).DE.gDatGralOpe
        emisor = general.gEmis
        receptor = general.gDatRec
        assert (
            emisor.dRucEm,
            emisor.dDVEmi,
            emisor.iTipCont,
            emisor.dNomEmi,
            emisor.dDirEmi,
            emisor.dEmailE,
        ) == (
            muestra.ruc_emisor,
            muestra.dv_emisor,
            muestra.tipo_contribuyente_emisor,
            muestra.nombre_emisor,
            muestra.direccion_emisor,
            muestra.email_emisor,
        )
        assert (receptor.dRucRec, receptor.dDVRec, receptor.dNomRec) == (
            muestra.ruc_receptor,
            muestra.dv_receptor,
            muestra.nombre_receptor,
        )

    @por_muestra
    def test_registro_items(self, muestra: Muestra) -> None:
        items = cargar(muestra).DE.gDtipDE.gCamItem
        assert len(items) == muestra.cantidad_items
        for item, esperado in zip(items, muestra.items):
            assert (
                item.dCodInt,
                item.dDesProSer,
                _valor(item.cUniMed),
                item.dCantProSer,
            ) == (
                esperado.codigo,
                esperado.descripcion,
                esperado.unidad,
                esperado.cantidad,
            )
            valor = item.gValorItem
            if esperado.precio_unitario is None:
                assert valor is None
            else:
                assert (valor.dPUniProSer, valor.dTotOpeItem) == (
                    esperado.precio_unitario,
                    esperado.total,
                )
            iva = item.gCamIVA
            if esperado.iva is None:
                assert iva is None
            else:
                assert (iva.dTasaIVA, iva.dBasGravIVA, iva.dLiqIVAItem) == (
                    esperado.tasa_iva,
                    esperado.base_gravada,
                    esperado.iva,
                )

    @por_muestra
    def test_registro_totales_y_pago(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        totales = de.gTotSub
        if muestra.total_general is None:
            assert totales is None
        else:
            assert (
                totales.dTotGralOpe,
                totales.dSub10,
                totales.dIVA10,
                totales.dTotIVA,
                totales.dBaseGrav10,
            ) == (
                muestra.total_general,
                muestra.subtotal_10,
                muestra.iva_10,
                muestra.total_iva,
                muestra.base_gravada_10,
            )
        condicion = de.gDtipDE.gCamCond
        if muestra.monto_pago is None:
            assert condicion is None
        else:
            montos = [pago.dMonTiPag for pago in condicion.gPaConEIni]
            assert montos == [muestra.monto_pago]

    @por_muestra
    def test_registro_grupos_del_tipo(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        especificos = de.gDtipDE
        notas = especificos.gCamNCDE
        if muestra.motivo is None:
            assert notas is None
        else:
            assert (_valor(notas.iMotEmi), _valor(notas.dDesMotEmi)) == (
                muestra.motivo,
                muestra.descripcion_motivo,
            )
        asociados = [asociado.dCdCDERef for asociado in de.gCamDEAsoc]
        esperados = [muestra.cdc_asociado] if muestra.cdc_asociado else []
        assert asociados == esperados
        autofactura = especificos.gCamAE
        if muestra.nombre_vendedor is None:
            assert autofactura is None
        else:
            assert (autofactura.dNomVen, autofactura.dNumIDVen) == (
                muestra.nombre_vendedor,
                muestra.id_vendedor,
            )
        remision = especificos.gCamNRE
        if muestra.motivo_traslado is None:
            assert remision is None
        else:
            assert [_valor(codigo) for codigo in remision.iMotEmiNR] == [
                muestra.motivo_traslado
            ]
            assert [_valor(texto) for texto in remision.dDesMotEmiNR] == [
                muestra.descripcion_motivo
            ]
        transporte = especificos.gTransp
        transportista = transporte.gCamTrans if transporte else None
        if muestra.ruc_transportista is None:
            assert transportista is None
        else:
            assert (transportista.dRucTrans, transportista.dDVTrans) == (
                muestra.ruc_transportista,
                muestra.dv_transportista,
            )

    @por_muestra
    def test_cdc_coherente_con_los_campos(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        emisor = de.gDatGralOpe.gEmis
        cdc = generate_cdc(
            i_tide=de.gTimb.iTiDE,
            d_ruc_em=emisor.dRucEm,
            d_dv_emi=emisor.dDVEmi,
            d_est=de.gTimb.dEst,
            d_pun_exp=de.gTimb.dPunExp,
            d_num_doc=de.gTimb.dNumDoc,
            i_tip_cont=emisor.iTipCont,
            d_fe_emi_de=de.gDatGralOpe.dFeEmiDE,
            i_tip_emi=de.gOpeDE.iTipEmi,
            d_cod_seg=de.gOpeDE.dCodSeg,
        )
        assert de.Id == cdc

    @por_muestra
    def test_dv_del_id_igual_a_ddvid(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        assert de.dDVId == de.Id[-1]

    @por_muestra
    def test_ruc_con_dv_correcto(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        emisor = de.gDatGralOpe.gEmis
        receptor = de.gDatGralOpe.gDatRec
        assert calculate_mod11_dv(emisor.dRucEm) == int(emisor.dDVEmi)
        assert calculate_mod11_dv(receptor.dRucRec) == int(receptor.dDVRec)
        transporte = de.gDtipDE.gTransp
        if transporte is not None and transporte.gCamTrans is not None:
            transportista = transporte.gCamTrans
            assert calculate_mod11_dv(transportista.dRucTrans) == int(
                transportista.dDVTrans
            )

    @por_muestra
    def test_cdc_asociado_es_una_factura_valida_del_emisor(
        self, muestra: Muestra
    ) -> None:
        de = cargar(muestra).DE
        emisor = de.gDatGralOpe.gEmis
        for asociado in de.gCamDEAsoc:
            cdc = asociado.dCdCDERef
            assert asociado.iTipDocAso.value == 1
            assert len(cdc) == 44
            assert cdc[:2] == "01"
            assert cdc[2:11] == emisor.dRucEm.zfill(8) + emisor.dDVEmi
            assert calculate_mod11_dv(cdc[:-1]) == int(cdc[-1])
            assert cdc[25:33] < de.gDatGralOpe.dFeEmiDE[:10].replace("-", "")

    @por_muestra
    def test_grupo_especifico_por_tipo(self, muestra: Muestra) -> None:
        especificos = cargar(muestra).DE.gDtipDE
        presentes = {
            grupo
            for grupo in _GRUPOS_DTIP
            if getattr(especificos, grupo) is not None
        }
        assert presentes == _GRUPOS_POR_TIPO[muestra.tipo]

    @por_muestra
    def test_operacion_comercial_segun_tipo(self, muestra: Muestra) -> None:
        operacion = cargar(muestra).DE.gDatGralOpe.gOpeCom
        if muestra.tipo == "7":
            assert operacion is None
            return
        assert _valor(operacion.cMoneOpe) == "PYG"
        tipo_transaccion = _valor(operacion.iTipTra)
        if muestra.tipo in {"5", "6"}:
            assert tipo_transaccion is None
        elif muestra.tipo == "4":
            assert tipo_transaccion in {10, 11}
        else:
            assert tipo_transaccion is not None

    @pytest.mark.parametrize(
        "muestra", [NOTA_CREDITO, NOTA_DEBITO], ids=lambda m: m.archivo
    )
    def test_motivo_de_nota_segun_tipo(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        assert _valor(de.gDtipDE.gCamNCDE.iMotEmi) in _MOTIVOS_POR_TIPO[muestra.tipo]
        assert len(de.gCamDEAsoc) >= 1

    def test_nota_remision_sin_valores_ni_totales(self) -> None:
        de = cargar(NOTA_REMISION).DE
        assert de.gTotSub is None
        for item in de.gDtipDE.gCamItem:
            assert item.gValorItem is None
            assert item.gCamIVA is None
        transporte = de.gDtipDE.gTransp
        assert transporte.iRespFlete is not None
        assert transporte.gCamSal is not None
        assert len(transporte.gCamEnt) >= 1
        assert len(transporte.gVehTras) >= 1
        assert transporte.gCamTrans is not None
        assert de.gDtipDE.gCamNRE.dKmR is not None

    def test_autofactura_sin_iva_y_receptor_igual_al_emisor(self) -> None:
        de = cargar(AUTOFACTURA).DE
        emisor = de.gDatGralOpe.gEmis
        receptor = de.gDatGralOpe.gDatRec
        assert (receptor.dRucRec, receptor.dDVRec, receptor.dNomRec) == (
            emisor.dRucEm,
            emisor.dDVEmi,
            emisor.dNomEmi,
        )
        for item in de.gDtipDE.gCamItem:
            assert item.gCamIVA is None
        totales = de.gTotSub
        for campo in ("dSub10", "dSub5", "dIVA10", "dIVA5", "dTotIVA", "dTBasGraIVA"):
            assert getattr(totales, campo) is None, campo
        assert de.gCamDEAsoc == []

    @por_muestra_con_totales
    def test_montos_coherentes(self, muestra: Muestra) -> None:
        de = cargar(muestra).DE
        subtotal = {5: Decimal(0), 10: Decimal(0)}
        base = {5: Decimal(0), 10: Decimal(0)}
        liquidado = {5: Decimal(0), 10: Decimal(0)}
        total_items = Decimal(0)
        for item in de.gDtipDE.gCamItem:
            valor = item.gValorItem
            assert valor.dTotOpeItem == (
                valor.dPUniProSer * item.dCantProSer - valor.dDescItem
            )
            assert valor.dTotOpeGs == valor.dTotOpeItem
            total_items += valor.dTotOpeItem
            iva = item.gCamIVA
            if iva is None:
                continue
            assert iva.dPropIVA == 100
            divisor = 1 + Decimal(iva.dTasaIVA) / 100
            base_item = (valor.dTotOpeItem / divisor).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            assert iva.dBasGravIVA == base_item
            assert iva.dLiqIVAItem == valor.dTotOpeItem - base_item
            subtotal[iva.dTasaIVA] += valor.dTotOpeItem
            base[iva.dTasaIVA] += base_item
            liquidado[iva.dTasaIVA] += iva.dLiqIVAItem
        totales = de.gTotSub
        assert totales.dTotOpe == total_items
        assert (
            totales.dTotDesc,
            totales.dDescTotal,
            totales.dAnticipo,
            totales.dRedon,
        ) == (0, 0, 0, 0)
        assert totales.dTotGralOpe == totales.dTotOpe
        assert totales.dTotalGs == totales.dTotGralOpe
        assert (totales.dSub5, totales.dSub10) == (
            _o_none(subtotal[5]),
            _o_none(subtotal[10]),
        )
        assert (totales.dIVA5, totales.dIVA10) == (
            _o_none(liquidado[5]),
            _o_none(liquidado[10]),
        )
        assert (totales.dBaseGrav5, totales.dBaseGrav10) == (
            _o_none(base[5]),
            _o_none(base[10]),
        )
        assert totales.dTotIVA == _o_none(liquidado[5] + liquidado[10])
        assert totales.dTBasGraIVA == _o_none(base[5] + base[10])
        condicion = de.gDtipDE.gCamCond
        if condicion is not None:
            pagado = sum(pago.dMonTiPag for pago in condicion.gPaConEIni)
            assert pagado == totales.dTotGralOpe

    @por_muestra
    def test_firma_de_relleno_declarada(self, muestra: Muestra) -> None:
        firma = cargar(muestra).Signature
        (referencia,) = firma.SignedInfo.Reference
        digest = referencia.DigestValue.value
        assert referencia.URI == f"#{muestra.cdc}"
        assert len(digest) == 32
        assert base64.b64encode(digest).decode() == muestra.digest_relleno
        assert (
            base64.b64encode(firma.SignatureValue.value).decode()
            == muestra.firma_relleno
        )

    @por_muestra
    def test_qr_regenerable_con_datos_del_registro(self, muestra: Muestra) -> None:
        rde = cargar(muestra)
        de = rde.DE
        totales = de.gTotSub
        esperado = generate_dcarqr(
            cdc=de.Id,
            d_fe_emi_de=de.gDatGralOpe.dFeEmiDE,
            digest_value=muestra.digest_relleno,
            id_csc=muestra.id_csc,
            csc=muestra.csc,
            d_ruc_rec=de.gDatGralOpe.gDatRec.dRucRec,
            d_tot_gral_ope=str(totales.dTotGralOpe) if totales else "0",
            d_tot_iva=(
                str(totales.dTotIVA)
                if totales is not None and totales.dTotIVA is not None
                else "0"
            ),
            c_items=str(len(de.gDtipDE.gCamItem)),
        )
        assert esperado.startswith(PREFIJO_QR_PRODUCCION)
        assert rde.gCamFuFD.dCarQR == esperado

    @por_muestra
    def test_qr_coincide_con_los_literales_del_xml(self, muestra: Muestra) -> None:
        # MT v150 §13.8.2: el QR lleva el texto de los campos del XML; la
        # autofactura no informa F017 y la remision no informa gTotSub, asi
        # que ambas llevan 0 (MT v150 p. 102; NT 10 §4, obs. 1).
        datos = (SAMPLES_DIR / muestra.archivo).read_bytes()
        esperado = generate_dcarqr_from_signed_xml(
            signed_xml=datos,
            id_csc=muestra.id_csc,
            csc=muestra.csc,
        )
        assert cargar(muestra).gCamFuFD.dCarQR == esperado
        assert ".00000000" not in esperado

    @por_muestra
    def test_lectura_sin_warnings_inesperados(self, muestra: Muestra) -> None:
        with warnings.catch_warnings(record=True) as capturadas:
            warnings.simplefilter("always")
            cargar(muestra)
        campos = set()
        for aviso in capturadas:
            assert issubclass(aviso.category, ConverterWarning), str(aviso.message)
            encontrado = _CAMPO_ADVERTENCIA.search(str(aviso.message))
            assert encontrado is not None, str(aviso.message)
            campos.add(encontrado.group(1))
        assert campos <= muestra.advertencias_admitidas

    def test_directorio_tiene_exactamente_las_muestras_del_registro(self) -> None:
        archivos = sorted(ruta.name for ruta in SAMPLES_DIR.glob("*.xml"))
        assert archivos == list(ARCHIVOS_MUESTRAS)

    @por_muestra
    def test_formato_de_archivo(self, muestra: Muestra) -> None:
        datos = (SAMPLES_DIR / muestra.archivo).read_bytes()
        assert not datos.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in datos
        assert b"\t" not in datos
        assert datos.split(b"\n", 1)[0] == DECLARACION_XML.encode("ascii")
        assert datos.endswith(b"\n")
        assert b"\n\n" not in datos
        assert b"<!--" not in datos
        for linea in datos.decode("utf-8").splitlines()[1:]:
            sangria = len(linea) - len(linea.lstrip(" "))
            assert sangria % 2 == 0, linea
            assert linea == linea.rstrip(), linea


# ---------------------------------------------------------------------------
# Validez contra el XSD v150 (procedimiento P-V150)
# ---------------------------------------------------------------------------

_DESCRIPCION_RESPONSABLE_NR = {
    "1": "Emisor de la factura",
    "2": "Poseedor de la factura y bienes",
    "3": "Empresa transportista",
}


def _q(nombre: str) -> str:
    """Nombre calificado en el namespace SIFEN."""
    return f"{{{NS_SIFEN}}}{nombre}"


def _elemento(nombre: str, texto: str) -> etree._Element:
    """Crea un elemento SIFEN con texto."""
    nodo = etree.Element(_q(nombre))
    nodo.text = texto
    return nodo


def _normalizar_a_v150(ruta: Path) -> etree._Element:
    """Aplica P-V150 sobre una copia en memoria de la muestra.

    Agrega los elementos que v150 exige y el binding ``fe_v141`` no admite, y
    quita los que solo existen en v141. Los tipos 2, 3 y 8 (paso que los
    convertia en factura) no tienen muestra, por lo que ese paso no aplica.
    """
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_blank_text=True
    )
    raiz = etree.parse(str(ruta), parser).getroot()
    de = raiz.find(_q("DE"))

    # 1. dSisFact inmediatamente despues de dFecFirma.
    de.find(_q("dFecFirma")).addnext(_elemento("dSisFact", "1"))

    # 2. v150 ya no admite la fecha de fin del timbrado.
    for nodo in list(de.iter(_q("dFeFinT"))):
        nodo.getparent().remove(nodo)

    # 4. gValorItem: total bruto y grupo gValorRestaItem.
    for valor in list(de.iter(_q("gValorItem"))):
        precio = valor.find(_q("dPUniProSer"))
        cantidad = Decimal(valor.getparent().findtext(_q("dCantProSer")))
        bruto = _elemento(
            "dTotBruOpeItem", format(Decimal(precio.text) * cantidad, "f")
        )
        resta = etree.Element(_q("gValorRestaItem"))
        for nombre in ("dDescItem", "dPorcDesIt", "dTotOpeItem", "dTotOpeGs"):
            hijo = valor.find(_q(nombre))
            if hijo is not None:
                resta.append(hijo)
        precio.addnext(bruto)
        bruto.addnext(resta)

    # 5. Base exenta por item.
    for iva in list(de.iter(_q("gCamIVA"))):
        iva.append(_elemento("dBasExe", "0"))

    # 6. Totales de descuentos y anticipos globales.
    descuento = de.find(f"{_q('gTotSub')}/{_q('dTotDesc')}")
    if descuento is not None:
        for nombre in ("dTotAnt", "dTotAntItem", "dTotDescGlotem"):
            descuento.addnext(_elemento(nombre, "0"))

    # 7. Autofactura: la constancia sale de gCamAE; entra la naturaleza.
    for autofactura in list(de.iter(_q("gCamAE"))):
        for nombre in ("iTipCons", "dDesTipCons", "dNumCons", "dNumControl"):
            hijo = autofactura.find(_q(nombre))
            if hijo is not None:
                autofactura.remove(hijo)
        autofactura.insert(0, _elemento("dDesNatVen", "No contribuyente"))
        autofactura.insert(0, _elemento("iNatVen", "1"))

    # 8. Remision: descripcion del responsable de la emision.
    for remision in list(de.iter(_q("gCamNRE"))):
        responsable = remision.find(_q("iRespEmiNR"))
        responsable.addnext(
            _elemento(
                "dDesRespEmiNR", _DESCRIPCION_RESPONSABLE_NR[responsable.text]
            )
        )

    # 9. Tipo de identificacion de cada vehiculo.
    for vehiculo in list(de.iter(_q("gVehTras"))):
        vehiculo.find(_q("dMarVeh")).addnext(_elemento("dTipIdenVeh", "1"))

    # 10. Domicilios del transportista y del chofer.
    for transportista in list(de.iter(_q("gCamTrans"))):
        chofer = transportista.find(_q("dNomChof"))
        chofer.addnext(_elemento("dDirChof", "Domicilio declarado del chofer"))
        chofer.addnext(_elemento("dDomFisc", "Domicilio fiscal del transportista"))

    return raiz


class TestValidezV150:
    """Validez de las muestras contra ``siRecepDE_v150.xsd``."""

    @por_muestra
    def test_muestra_valida_tras_normalizar(self, muestra: Muestra) -> None:
        raiz = _normalizar_a_v150(SAMPLES_DIR / muestra.archivo)
        assert validate_xml(etree.tostring(raiz, encoding="unicode")) == []

    @por_muestra
    def test_validate_xml_solo_reporta_dsisfact(self, muestra: Muestra) -> None:
        # Limitacion conocida: el binding fe_v141 no puede emitir dSisFact.
        errores = cargar(muestra).validate_xml()
        assert len(errores) == 1, errores
        assert "dSisFact" in errores[0]


class TestFirmaDeMuestras:
    """Firmar una muestra reemplaza la firma de relleno por una sola real."""

    @por_muestra
    def test_firma_reemplaza_la_de_relleno(self, muestra: Muestra) -> None:
        pytest.importorskip("signxml")
        from kilasifen.engine.firma import sign_xml

        rde = cargar(muestra)
        firmado = sign_xml(
            rde.to_xml(),
            CERTIFICADO_PRUEBA.read_bytes(),
            CLAVE_CERTIFICADO_PRUEBA,
            rde.DE.Id,
        )
        raiz = etree.fromstring(firmado.encode("utf-8"))
        firmas = list(raiz.iter(f"{{{NS_DS}}}Signature"))
        assert len(firmas) == 1
        referencias = firmas[0].findall(f".//{{{NS_DS}}}Reference")
        assert [ref.get("URI") for ref in referencias] == [f"#{muestra.cdc}"]
        assert [etree.QName(hijo).localname for hijo in raiz] == [
            "dVerFor",
            "DE",
            "Signature",
            "gCamFuFD",
        ]
        assert muestra.digest_relleno not in firmado
        assert muestra.firma_relleno not in firmado
