"""Build unsigned SIFEN XML from typed document contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

from kilasifen.domain.common.paraguay_time import (
    format_sifen_datetime,
    paraguay_now,
)
from kilasifen.domain.documents.emitter_identity import (
    find_emitter_identity_mismatch,
)
from kilasifen.domain.documents.fiscal_dates import parse_sifen_datetime
from kilasifen.domain.documents.models import Document
from kilasifen.domain.documents.receiver import (
    Receiver,
    ReceiverRuleError,
    innominado_limit_error,
    resolve_receiver,
)
from kilasifen.domain.documents.security_code import (
    InvalidSecurityCodeError,
    normalize_security_code,
)
from kilasifen.domain.emitters.fiscal_profile import (
    EmitterFiscalProfile,
    FiscalAddress,
)
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.catalogos import (
    descripcion_departamento,
    descripcion_pais,
)
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv, generate_cdc
from kilasifen.engine.sdk.validation import validate_xml

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
ET.register_namespace("", SIFEN_NS)

_ZERO = Decimal("0")
_AMOUNT_Q = Decimal("0.00000001")
_AMOUNT4_Q = Decimal("0.0001")
_PERCENT_Q = Decimal("0.00000001")
_ITEM_TOTAL_Q = Decimal("0.00000001")
#: Literal that MT v150 validation 1263 (D105) requires in the test
#: environment and forbids in production.
MT_TEST_EMITTER_NAME = (
    "DE generado en ambiente de prueba - sin valor comercial ni fiscal"
)
#: A qualified ``ds:`` tag (opening or closing) or an ``xmlns:ds`` declaration.
_DS_PREFIX_PATTERN = re.compile(r"</?ds:|\sxmlns:ds\s*=")

_TRANSACTION_CODE_BY_NAME = {
    "venta_mercaderia": 1,
    "prestacion_servicios": 2,
    "mixto": 3,
    "venta_activo_fijo": 4,
    "venta_divisas": 5,
    "compra_divisas": 6,
    "promocion": 7,
    "donacion": 8,
    "anticipo": 9,
    "compra_productos": 10,
    "compra_servicios": 11,
    "venta_credito_fiscal": 12,
    "muestras_medicas": 13,
}
_TRANSACTION_DESCRIPTION_BY_CODE = {
    1: "Venta de mercadería",
    2: "Prestación de servicios",
    3: "Mixto (Venta de mercadería y servicios)",
    4: "Venta de activo fijo",
    5: "Venta de divisas",
    6: "Compra de divisas",
    7: "Promoción o entrega de muestras",
    8: "Donación",
    9: "Anticipo",
    10: "Compra de productos",
    11: "Compra de servicios",
    12: "Venta de crédito fiscal",
    13: "Muestras médicas (Art. 3 RG 24/2014)",
}
_TAX_CODE_BY_NAME = {
    "iva": 1,
    "isc": 2,
    "renta": 3,
    "ninguno": 4,
    "iva_renta": 5,
}
_TAX_DESCRIPTION_BY_CODE = {
    1: "IVA",
    2: "ISC",
    3: "Renta",
    4: "Ninguno",
    5: "IVA - Renta",
}
_PRESENCE_CODE_BY_NAME = {
    "presencial": 1,
    "electronica": 2,
    "telemarketing": 3,
    "domicilio": 4,
    "bancaria": 5,
    "ciclica": 6,
    "otro": 9,
}
_PRESENCE_DESCRIPTION_BY_CODE = {
    1: "Operación presencial",
    2: "Operación electrónica",
    3: "Operación telemarketing",
    4: "Venta a domicilio",
    5: "Operación bancaria",
    6: "Operación cíclica",
    9: "Otra modalidad",
}
_PAYMENT_TYPE_CODE_BY_NAME = {
    "efectivo": 1,
    "cheque": 2,
    "tarjeta_credito": 3,
    "tarjeta_debito": 4,
    "transferencia": 5,
    "giro": 6,
    "billetera_electronica": 7,
    "tarjeta_empresarial": 8,
    "vale": 9,
    "retencion": 10,
    "anticipo": 11,
    "valor_fiscal": 12,
    "valor_comercial": 13,
    "compensacion": 14,
    "permuta": 15,
    "pago_bancario": 16,
    "pago_movil": 17,
    "donacion": 18,
    "promocion": 19,
    "consumo_interno": 20,
    "pago_electronico": 21,
    "otro": 99,
}
_PAYMENT_DESCRIPTION_BY_TYPE = {
    1: "Efectivo",
    2: "Cheque",
    3: "Tarjeta de crédito",
    4: "Tarjeta de débito",
    5: "Transferencia",
    6: "Giro",
    7: "Billetera electrónica",
    8: "Tarjeta empresarial",
    9: "Vale",
    10: "Retención",
    11: "Pago por anticipo",
    12: "Valor fiscal",
    13: "Valor comercial",
    14: "Compensación",
    15: "Permuta",
    16: "Pago bancario",
    17: "Pago Móvil",
    18: "Donación",
    19: "Promoción",
    20: "Consumo Interno",
    21: "Pago Electrónico",
    99: "Otro",
}
_CARD_BRAND_CODE_BY_NAME = {
    "visa": 1,
    "mastercard": 2,
    "american_express": 3,
    "maestro": 4,
    "panal": 5,
    "cabal": 6,
    "otro": 99,
}
_CARD_BRAND_DESCRIPTION_BY_CODE = {
    1: "Visa",
    2: "Mastercard",
    3: "American Express",
    4: "Maestro",
    5: "Panal",
    6: "Cabal",
    99: "Otro",
}
_CARD_PROCESSING_CODE_BY_NAME = {
    "pos": 1,
    "electronico": 2,
    "otro": 9,
}
_AFFECTATION_CODE_BY_NAME = {
    "gravado": 1,
    "exonerado": 2,
    "exento": 3,
    "gravado_parcial": 4,
}
_AFFECTATION_DESCRIPTION_BY_CODE = {
    1: "Gravado IVA",
    2: "Exonerado (Art. 83- Ley 125/91)",
    3: "Exento",
    4: "Gravado parcial (Grav- Exento)",
}
#: D141/D142: XSD tiTipIDRespDE ([1-4]|9) and tdDTipIDRespDE. With 9 the
#: real document type is given in 9-41 characters (NT 10 §2.2, 1265).
_RESPONSIBLE_ID_TYPE_DESCRIPTION = {
    1: "Cédula paraguaya",
    2: "Pasaporte",
    3: "Cédula extranjera",
    4: "Carnet de residencia",
}
_RESPONSIBLE_OTHER_ID_TYPE = 9
_MOTIVE_CODE_BY_NAME = {
    "devolucion_y_ajuste": 1,
    "devolucion": 2,
    "descuento": 3,
    "bonificacion": 4,
    "credito_incobrable": 5,
    "recupero_costo": 6,
    "recupero_gasto": 7,
    "ajuste_precio": 8,
}
_MOTIVE_DESCRIPTION_BY_CODE = {
    1: "Devolución y Ajuste de precios",
    2: "Devolución",
    3: "Descuento",
    4: "Bonificación",
    5: "Crédito incobrable",
    6: "Recupero de costo",
    7: "Recupero de gasto",
    8: "Ajuste de precio",
}
_ASSOCIATED_DOC_TYPE_DESCRIPTION = {
    1: "Electrónico",
    2: "Impreso",
    3: "Constancia Electrónica",
}
_PRINTED_DOC_TYPE_DESCRIPTION = {
    1: "Factura",
    2: "Nota de crédito",
    3: "Nota de débito",
    4: "Nota de remisión",
}


@dataclass(slots=True)
class TypedXmlBuildResult:
    """Unsigned XML generated from a typed document contract."""

    generated_xml: str
    doc_id: str


@dataclass(frozen=True, slots=True)
class _Issuer:
    """``gEmis`` data of one document, all taken from the registered emitter."""

    ruc: str
    dv: str
    name: str
    profile: EmitterFiscalProfile
    address: FiscalAddress


@dataclass(slots=True)
class _ItemComputation:
    amount_exe: Decimal
    amount_exo: Decimal
    amount_5: Decimal
    amount_10: Decimal
    discount_particular: Decimal
    discount_global: Decimal
    anticipo_particular: Decimal
    anticipo_global: Decimal
    base_5: Decimal
    base_10: Decimal
    iva_5: Decimal
    iva_10: Decimal
    total_gs: Decimal | None


@dataclass(slots=True)
class _Totals:
    sub_exe: Decimal
    sub_exo: Decimal
    sub_5: Decimal
    sub_10: Decimal
    total: Decimal
    total_discount_particular: Decimal
    total_discount_global: Decimal
    total_anticipo_particular: Decimal
    total_anticipo_global: Decimal
    base_5: Decimal
    base_10: Decimal
    iva_5: Decimal
    iva_10: Decimal
    redondeo: Decimal
    total_neto: Decimal
    total_iva: Decimal
    total_gs: Decimal | None


def build_typed_document_xml(
    *,
    document: Document,
    emitter: Emitter,
    stamping: Stamping,
    test_emitter_name_literal: str | None = None,
    signed_at: datetime | None = None,
) -> TypedXmlBuildResult | None:
    """Build unsigned XML when payload includes a supported typed contract.

    ``test_emitter_name_literal`` replaces ``dNomEmi`` for emitters of the
    SIFEN test environment (validation 1263); ``None`` keeps the legal name.
    ``signed_at`` is the moment the XML will be signed, written as
    ``dFecFirma``; it defaults to now.
    """

    fecha_firma = format_sifen_datetime(signed_at or paraguay_now())

    payload = document.payload_snapshot or {}
    typed_contract = payload.get("typed_contract")
    if not isinstance(typed_contract, dict):
        return None
    contract = str(typed_contract.get("contract") or "").strip()
    typed_payload = typed_contract.get("payload")
    if not isinstance(typed_payload, dict):
        raise SifenValidationError("typed_contract.payload must be an object")

    if contract == "factura_v1":
        return _build_factura_xml(
            typed_payload=typed_payload,
            emitter=emitter,
            stamping=stamping,
            test_emitter_name_literal=test_emitter_name_literal,
            security_code=document.security_code,
            fecha_firma=fecha_firma,
        )
    if contract == "nota_credito_v1":
        return _build_adjustment_note_xml(
            typed_payload=typed_payload,
            emitter=emitter,
            stamping=stamping,
            test_emitter_name_literal=test_emitter_name_literal,
            security_code=document.security_code,
            fecha_firma=fecha_firma,
            document_type_code=5,
            document_type_description="Nota de crédito electrónica",
        )
    if contract == "nota_debito_v1":
        return _build_adjustment_note_xml(
            typed_payload=typed_payload,
            emitter=emitter,
            stamping=stamping,
            test_emitter_name_literal=test_emitter_name_literal,
            security_code=document.security_code,
            fecha_firma=fecha_firma,
            document_type_code=6,
            document_type_description="Nota de débito electrónica",
        )
    return None


def _build_factura_xml(
    *,
    typed_payload: dict,
    emitter: Emitter,
    stamping: Stamping,
    test_emitter_name_literal: str | None,
    security_code: str | None,
    fecha_firma: str,
) -> TypedXmlBuildResult:
    numero_documento = _required_intlike(typed_payload, "numero")
    fecha_emision = _resolve_emission_datetime(typed_payload)
    establecimiento = _normalize_three_digits(
        typed_payload.get("establecimiento"), "001"
    )
    punto = _normalize_three_digits(typed_payload.get("punto"), "001")
    codigo_seguridad = _resolve_security_code(
        security_code, typed_payload, numero_documento
    )
    issuer = _resolve_issuer(
        emitter=emitter,
        typed_payload=typed_payload,
        establecimiento=establecimiento,
        test_emitter_name_literal=test_emitter_name_literal,
    )
    cliente = _required_object(typed_payload, "cliente")
    items = _required_items(typed_payload)

    tipo_transaccion = _resolve_code(
        typed_payload.get("tipo_transaccion"),
        mapping=_TRANSACTION_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=13,
        field_name="tipo_transaccion",
    )
    tipo_impuesto = _resolve_code(
        typed_payload.get("tipo_impuesto"),
        mapping=_TAX_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=5,
        field_name="tipo_impuesto",
    )
    indicador_presencia = _resolve_code(
        typed_payload.get("indicador_presencia"),
        mapping=_PRESENCE_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=9,
        field_name="indicador_presencia",
    )
    moneda, moneda_descripcion, condicion_tipo_cambio, tipo_cambio = (
        _resolve_currency_data(typed_payload)
    )
    item_computations = _append_items(
        dtip=None,  # created later once DE structure exists
        items=items,
        moneda=moneda,
        condicion_tipo_cambio=condicion_tipo_cambio,
    )
    totals = _calculate_totals(item_computations, moneda=moneda)
    totals.total_gs = _resolve_total_gs(
        totals=totals,
        item_computations=item_computations,
        moneda=moneda,
        condicion_tipo_cambio=condicion_tipo_cambio,
        tipo_cambio=tipo_cambio,
    )
    _assert_totals_consistency(totals)
    receiver = _resolve_receiver(cliente, document_type=1)
    _assert_innominado_limit(
        receiver,
        transaction_type=tipo_transaccion,
        currency=moneda,
        totals=totals,
    )

    doc_id = _build_doc_id(
        i_tide=1,
        issuer=issuer,
        fecha_emision=fecha_emision,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        codigo_seguridad=codigo_seguridad,
    )
    root = _build_base_document_root(
        doc_id=doc_id,
        fecha_emision=fecha_emision,
        fecha_firma=fecha_firma,
        i_tide=1,
        d_des_tide="Factura electrónica",
        stamping=stamping,
        issuer=issuer,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        codigo_seguridad=codigo_seguridad,
        typed_payload=typed_payload,
        receiver=receiver,
        tipo_transaccion=tipo_transaccion,
        include_tipo_transaccion=True,
        tipo_impuesto=tipo_impuesto,
        moneda=moneda,
        moneda_descripcion=moneda_descripcion,
        condicion_tipo_cambio=condicion_tipo_cambio,
        tipo_cambio=tipo_cambio,
    )

    de = _find_de(root)
    dtip = _sub(de, "gDtipDE")
    gcam_fe = _sub(dtip, "gCamFE")
    _sub(gcam_fe, "iIndPres", str(indicador_presencia))
    _sub(gcam_fe, "dDesIndPres", _presence_description(indicador_presencia))
    if receiver.operation_type == 3:
        _append_public_procurement_group(gcam_fe=gcam_fe, cliente=cliente)

    _append_condition_node(
        dtip=dtip,
        typed_payload=typed_payload,
        total=totals.total_neto,
        moneda=moneda,
        moneda_descripcion=moneda_descripcion,
        tipo_cambio=tipo_cambio,
    )
    _append_items(
        dtip=dtip,
        items=items,
        moneda=moneda,
        condicion_tipo_cambio=condicion_tipo_cambio,
    )
    _append_totals(de, totals)
    _append_associated_documents_if_any(de=de, typed_payload=typed_payload)
    _append_outside_signature_group(
        root=root,
        dcarqr=_resolve_dcarqr_value(
            typed_payload=typed_payload,
            doc_id=doc_id,
            fecha_emision=fecha_emision,
            receptor=_resolve_qr_receptor(cliente),
            total_neto=totals.total_neto,
            total_iva=totals.total_iva,
            items_count=len(items),
        ),
    )

    generated_xml = _finalize_xml(root)
    return TypedXmlBuildResult(generated_xml=generated_xml, doc_id=doc_id)


def _build_adjustment_note_xml(
    *,
    typed_payload: dict,
    emitter: Emitter,
    stamping: Stamping,
    test_emitter_name_literal: str | None,
    security_code: str | None,
    fecha_firma: str,
    document_type_code: int,
    document_type_description: str,
) -> TypedXmlBuildResult:
    numero_documento = _required_intlike(typed_payload, "numero")
    fecha_emision = _resolve_emission_datetime(typed_payload)
    establecimiento = _normalize_three_digits(
        typed_payload.get("establecimiento"), "001"
    )
    punto = _normalize_three_digits(typed_payload.get("punto"), "001")
    codigo_seguridad = _resolve_security_code(
        security_code, typed_payload, numero_documento
    )
    issuer = _resolve_issuer(
        emitter=emitter,
        typed_payload=typed_payload,
        establecimiento=establecimiento,
        test_emitter_name_literal=test_emitter_name_literal,
    )
    cliente = _required_object(typed_payload, "cliente")
    items = _required_items(typed_payload)
    asociado = _required_object(typed_payload, "documento_asociado")

    tipo_transaccion = _resolve_code(
        typed_payload.get("tipo_transaccion"),
        mapping=_TRANSACTION_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=13,
        field_name="tipo_transaccion",
    )
    tipo_impuesto = _resolve_code(
        typed_payload.get("tipo_impuesto"),
        mapping=_TAX_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=5,
        field_name="tipo_impuesto",
    )
    moneda, moneda_descripcion, condicion_tipo_cambio, tipo_cambio = (
        _resolve_currency_data(typed_payload)
    )

    item_computations = _append_items(
        dtip=None,
        items=items,
        moneda=moneda,
        condicion_tipo_cambio=condicion_tipo_cambio,
    )
    totals = _calculate_totals(item_computations, moneda=moneda)
    totals.total_gs = _resolve_total_gs(
        totals=totals,
        item_computations=item_computations,
        moneda=moneda,
        condicion_tipo_cambio=condicion_tipo_cambio,
        tipo_cambio=tipo_cambio,
    )
    _assert_totals_consistency(totals)
    receiver = _resolve_receiver(cliente, document_type=document_type_code)

    doc_id = _build_doc_id(
        i_tide=document_type_code,
        issuer=issuer,
        fecha_emision=fecha_emision,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        codigo_seguridad=codigo_seguridad,
    )
    root = _build_base_document_root(
        doc_id=doc_id,
        fecha_emision=fecha_emision,
        fecha_firma=fecha_firma,
        i_tide=document_type_code,
        d_des_tide=document_type_description,
        stamping=stamping,
        issuer=issuer,
        establecimiento=establecimiento,
        punto=punto,
        numero_documento=numero_documento,
        codigo_seguridad=codigo_seguridad,
        typed_payload=typed_payload,
        receiver=receiver,
        tipo_transaccion=tipo_transaccion,
        include_tipo_transaccion=False,
        tipo_impuesto=tipo_impuesto,
        moneda=moneda,
        moneda_descripcion=moneda_descripcion,
        condicion_tipo_cambio=condicion_tipo_cambio,
        tipo_cambio=tipo_cambio,
    )

    de = _find_de(root)
    dtip = _sub(de, "gDtipDE")
    gcam_ncde = _sub(dtip, "gCamNCDE")
    motivo = _resolve_code(
        typed_payload.get("motivo_emision"),
        mapping=_MOTIVE_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=8,
        field_name="motivo_emision",
    )
    _sub(gcam_ncde, "iMotEmi", str(motivo))
    _sub(gcam_ncde, "dDesMotEmi", _nota_credito_motive_description(motivo))

    _append_items(
        dtip=dtip,
        items=items,
        moneda=moneda,
        condicion_tipo_cambio=condicion_tipo_cambio,
    )
    _append_totals(de, totals)
    _append_associated_document(de=de, asociado=asociado, required=True)
    _append_outside_signature_group(
        root=root,
        dcarqr=_resolve_dcarqr_value(
            typed_payload=typed_payload,
            doc_id=doc_id,
            fecha_emision=fecha_emision,
            receptor=_resolve_qr_receptor(cliente),
            total_neto=totals.total_neto,
            total_iva=totals.total_iva,
            items_count=len(items),
        ),
    )

    generated_xml = _finalize_xml(root)
    return TypedXmlBuildResult(generated_xml=generated_xml, doc_id=doc_id)


def _build_base_document_root(
    *,
    doc_id: str,
    fecha_emision: str,
    fecha_firma: str,
    i_tide: int,
    d_des_tide: str,
    stamping: Stamping,
    issuer: _Issuer,
    establecimiento: str,
    punto: str,
    numero_documento: int,
    codigo_seguridad: str,
    typed_payload: dict,
    receiver: Receiver,
    tipo_transaccion: int,
    include_tipo_transaccion: bool,
    tipo_impuesto: int,
    moneda: str,
    moneda_descripcion: str,
    condicion_tipo_cambio: int | None,
    tipo_cambio: Decimal | None,
) -> ET.Element:
    root = ET.Element(_tag("rDE"))
    _sub(root, "dVerFor", "150")
    de = _sub(root, "DE")
    de.set("Id", doc_id)
    _sub(de, "dDVId", str(calculate_mod11_dv(doc_id[:-1])))
    # A004: the real signing time (RG 23/2019 Art. 13), not dFeEmiDE.
    _sub(de, "dFecFirma", fecha_firma)
    _sub(de, "dSisFact", "1")

    gope = _sub(de, "gOpeDE")
    _sub(gope, "iTipEmi", "1")
    _sub(gope, "dDesTipEmi", "Normal")
    _sub(gope, "dCodSeg", codigo_seguridad)

    gtimb = _sub(de, "gTimb")
    _sub(gtimb, "iTiDE", str(i_tide))
    _sub(gtimb, "dDesTiDE", d_des_tide)
    _sub(gtimb, "dNumTim", str(stamping.number))
    _sub(gtimb, "dEst", establecimiento)
    _sub(gtimb, "dPunExp", punto)
    _sub(gtimb, "dNumDoc", f"{numero_documento:07d}")
    _sub(gtimb, "dFeIniT", stamping.start_date.isoformat())

    gdat = _sub(de, "gDatGralOpe")
    _sub(gdat, "dFeEmiDE", fecha_emision)
    ope = _sub(gdat, "gOpeCom")
    if include_tipo_transaccion:
        _sub(ope, "iTipTra", str(tipo_transaccion))
        _sub(ope, "dDesTipTra", _transaction_description(tipo_transaccion))
    _sub(ope, "iTImp", str(tipo_impuesto))
    _sub(ope, "dDesTImp", _tax_description(tipo_impuesto))
    _sub(ope, "cMoneOpe", moneda)
    _sub(ope, "dDesMoneOpe", moneda_descripcion)
    if moneda != "PYG":
        if condicion_tipo_cambio is None:
            raise SifenValidationError(
                "documents.currency.condicion_tipo_cambio_required"
            )
        _sub(ope, "dCondTiCam", str(condicion_tipo_cambio))
        if condicion_tipo_cambio == 1:
            if tipo_cambio is None:
                raise SifenValidationError("documents.currency.tipo_cambio_required")
            _sub(ope, "dTiCam", _as_sifen_amount4(tipo_cambio))
    elif condicion_tipo_cambio is not None or tipo_cambio is not None:
        raise SifenValidationError(
            "documents.currency.condicion_tipo_cambio_not_allowed"
        )

    _append_anticipation_condition(ope=ope, typed_payload=typed_payload)

    _append_issuer(gdat=gdat, issuer=issuer, typed_payload=typed_payload)
    _append_receiver(gdat=gdat, receiver=receiver)
    return root


def _resolve_issuer(
    *,
    emitter: Emitter,
    typed_payload: dict,
    establecimiento: str,
    test_emitter_name_literal: str | None,
) -> _Issuer:
    """Take every gEmis value from the registered emitter (MT v150 D101-D132)."""

    profile = emitter.fiscal_profile
    if profile is None:
        raise SifenValidationError("emitters.fiscal_profile_required")
    mismatch = find_emitter_identity_mismatch(
        typed_payload,
        ruc=emitter.ruc,
        dv=emitter.dv,
        legal_name=emitter.legal_name,
        taxpayer_type=profile.taxpayer_type,
    )
    if mismatch is not None:
        raise SifenValidationError(f"documents.emisor.identity_mismatch:{mismatch}")
    return _Issuer(
        ruc=emitter.ruc,
        dv=emitter.dv,
        name=_issuer_name(emitter, test_emitter_name_literal),
        profile=profile,
        address=profile.address_for(establecimiento),
    )


def _issuer_name(emitter: Emitter, test_emitter_name_literal: str | None) -> str:
    """dNomEmi (D105): the test literal only applies to test emitters (1263)."""

    if emitter.tax_environment == "test":
        return test_emitter_name_literal or emitter.legal_name
    if emitter.legal_name.strip().casefold() == MT_TEST_EMITTER_NAME.casefold():
        # 1263: the test literal must not be used in production.
        raise SifenValidationError("documents.emisor.test_name_in_production")
    return emitter.legal_name


def _append_issuer(*, gdat: ET.Element, issuer: _Issuer, typed_payload: dict) -> None:
    profile = issuer.profile
    address = issuer.address
    emis = _sub(gdat, "gEmis")
    _sub(emis, "dRucEm", issuer.ruc)
    _sub(emis, "dDVEmi", issuer.dv)
    _sub(emis, "iTipCont", str(profile.taxpayer_type))
    if profile.regime_type is not None:
        _sub(emis, "cTipReg", str(profile.regime_type))
    _sub(emis, "dNomEmi", issuer.name)
    if profile.trade_name:
        _sub(emis, "dNomFanEmi", profile.trade_name)
    _sub(emis, "dDirEmi", address.street)
    _sub(emis, "dNumCas", address.house_number)
    if address.complement_1:
        _sub(emis, "dCompDir1", address.complement_1)
    if address.complement_2:
        _sub(emis, "dCompDir2", address.complement_2)
    _sub(emis, "cDepEmi", str(address.department_code))
    _sub(emis, "dDesDepEmi", address.department_description)
    if address.district_code is not None:
        _sub(emis, "cDisEmi", str(address.district_code))
        _sub(emis, "dDesDisEmi", address.district_description)
    _sub(emis, "cCiuEmi", str(address.city_code))
    _sub(emis, "dDesCiuEmi", address.city_description)
    _sub(emis, "dTelEmi", address.phone)
    _sub(emis, "dEmailE", address.email)
    if address.branch_name:
        _sub(emis, "dDenSuc", address.branch_name)
    for activity in profile.activities:
        gact = _sub(emis, "gActEco")
        _sub(gact, "cActEco", activity.code)
        _sub(gact, "dDesActEco", activity.description)
    emisor_payload = typed_payload.get("emisor")
    responsable = (
        emisor_payload.get("responsable_generacion")
        if isinstance(emisor_payload, dict)
        else None
    )
    if isinstance(responsable, dict):
        _append_generation_responsible(emis=emis, responsable=responsable)


def _append_generation_responsible(*, emis: ET.Element, responsable: dict) -> None:
    """gRespDE (D140-D145): every value comes from the payload, none defaulted."""

    tipo = _coerce_int(
        _first_non_none(responsable, "tipo_documento", "tipo_id"),
        field_name="emisor.responsable_generacion.tipo_documento",
    )
    if tipo == _RESPONSIBLE_OTHER_ID_TYPE:
        descripcion = _clean_text(responsable.get("descripcion_tipo_documento"))
        if descripcion is None or not 9 <= len(descripcion) <= 41:
            raise SifenValidationError(
                "documents.emisor.responsable_generacion.descripcion_tipo_documento"
            )
    elif tipo in _RESPONSIBLE_ID_TYPE_DESCRIPTION:
        descripcion = _RESPONSIBLE_ID_TYPE_DESCRIPTION[tipo]
    else:
        raise SifenValidationError(
            "documents.emisor.responsable_generacion.tipo_documento_invalid"
        )
    numero = _clean_text(_first_non_none(responsable, "numero_documento", "numero"))
    nombre = _clean_text(_first_non_none(responsable, "nombre", "razon_social"))
    cargo = _clean_text(responsable.get("cargo"))
    if not numero or not nombre or not cargo or not 4 <= len(cargo) <= 100:
        raise SifenValidationError("documents.emisor.responsable_generacion_invalid")
    gresp = _sub(emis, "gRespDE")
    _sub(gresp, "iTipIDRespDE", str(tipo))
    _sub(gresp, "dDTipIDRespDE", descripcion)
    _sub(gresp, "dNumIDRespDE", numero)
    _sub(gresp, "dNomRespDE", nombre)
    _sub(gresp, "dCarRespDE", cargo)


def _resolve_receiver(cliente: dict, *, document_type: int) -> Receiver:
    """Apply the gDatRec rules in force (see kilasifen.domain.documents.receiver)."""

    try:
        return resolve_receiver(
            cliente,
            document_type=document_type,
            country_description=descripcion_pais,
            department_description=descripcion_departamento,
            mod11_dv=calculate_mod11_dv,
        )
    except ReceiverRuleError as exc:
        raise SifenValidationError(exc.code) from exc


def _assert_innominado_limit(
    receiver: Receiver,
    *,
    transaction_type: int,
    currency: str,
    totals: _Totals,
) -> None:
    """1321 (NT 24): innominado below 7.000.000 Gs (F014, or F023 if not PYG)."""

    error = innominado_limit_error(
        receiver,
        transaction_type=transaction_type,
        currency=currency,
        total_operation=totals.total_neto,
        total_guaranies=totals.total_gs,
    )
    if error is not None:
        raise SifenValidationError(error)


def _append_receiver(*, gdat: ET.Element, receiver: Receiver) -> None:
    rec = _sub(gdat, "gDatRec")
    _sub(rec, "iNatRec", str(receiver.nature))
    _sub(rec, "iTiOpe", str(receiver.operation_type))
    _sub(rec, "cPaisRec", receiver.country_code)
    _sub(rec, "dDesPaisRe", receiver.country_description)
    if receiver.nature == 1:
        _sub(rec, "iTiContRec", str(receiver.taxpayer_type))
        _sub(rec, "dRucRec", receiver.ruc)
        _sub(rec, "dDVRec", receiver.dv)
    else:
        _sub(rec, "iTipIDRec", str(receiver.id_type))
        _sub(rec, "dDTipIDRec", receiver.id_type_description)
        _sub(rec, "dNumIDRec", receiver.id_number)
    _sub(rec, "dNomRec", receiver.name)
    address = receiver.address
    if address is not None:
        optional_fields = (
            ("dDirRec", address.street),
            ("dNumCasRec", address.house_number),
            ("cDepRec", address.department_code),
            ("dDesDepRec", address.department_description),
            ("cDisRec", address.district_code),
            ("dDesDisRec", address.district_description),
            ("cCiuRec", address.city_code),
            ("dDesCiuRec", address.city_description),
        )
        for tag, value in optional_fields:
            if value is not None:
                _sub(rec, tag, str(value))
    for tag, value in (
        ("dTelRec", receiver.phone),
        ("dCelRec", receiver.cellphone),
        ("dEmailRec", receiver.email),
        ("dCodCliente", receiver.customer_code),
    ):
        if value is not None:
            _sub(rec, tag, value)


def _append_public_procurement_group(*, gcam_fe: ET.Element, cliente: dict) -> None:
    # NT 26 (prod 16/06/2025): E020 gCompPub is optional in B2G.
    compras = cliente.get("compras_publicas")
    if compras is None:
        return
    if not isinstance(compras, dict):
        raise SifenValidationError("documents.cliente.compras_publicas_invalid")
    modalidad = _clean_text(_first_non_none(compras, "modalidad_dncp", "modalidad"))
    entidad = _clean_text(compras.get("entidad"))
    anio = _clean_text(compras.get("anio"))
    secuencia = _clean_text(compras.get("secuencia"))
    fecha_codigo = _resolve_date(
        _first_non_none(compras, "fecha_codigo", "fecha")
    ).isoformat()
    if not modalidad or not entidad or not anio or not secuencia:
        raise SifenValidationError("documents.cliente.compras_publicas_invalid")
    gcomp = _sub(gcam_fe, "gCompPub")
    _sub(gcomp, "dModCont", f"{int(modalidad):02d}")
    _sub(gcomp, "dEntCont", f"{int(entidad):05d}")
    _sub(gcomp, "dAnoCont", str(int(anio)))
    _sub(gcomp, "dSecCont", f"{int(secuencia):07d}")
    _sub(gcomp, "dFeCodCont", fecha_codigo)


def _append_anticipation_condition(*, ope: ET.Element, typed_payload: dict) -> None:
    items = typed_payload.get("items")
    if not isinstance(items, list) or not items:
        return
    has_global = False
    has_item = False
    for item in items:
        if not isinstance(item, dict):
            continue
        anticipo_global = _coerce_decimal(
            _first_non_none(item, "anticipo_global", "dAntGloPreUniIt"),
            field_name="items.anticipo_global",
            default=_ZERO,
        )
        anticipo_particular = _coerce_decimal(
            _first_non_none(item, "anticipo_particular", "dAntPreUniIt"),
            field_name="items.anticipo_particular",
            default=_ZERO,
        )
        if anticipo_global > _ZERO:
            has_global = True
        if anticipo_particular > _ZERO:
            has_item = True
    if has_global:
        _sub(ope, "iCondAnt", "1")
        _sub(ope, "dDesCondAnt", "Anticipo Global")
    elif has_item:
        _sub(ope, "iCondAnt", "2")
        _sub(ope, "dDesCondAnt", "Anticipo por Ítem")


def _append_condition_node(
    *,
    dtip: ET.Element,
    typed_payload: dict,
    total: Decimal,
    moneda: str,
    moneda_descripcion: str,
    tipo_cambio: Decimal | None,
) -> None:
    condicion_payload = _resolve_condition_payload(typed_payload)
    condicion = _resolve_code(
        _first_non_none(condicion_payload, "tipo", "iCondOpe", "condicion_operacion"),
        mapping={"contado": 1, "credito": 2},
        default=1,
        min_value=1,
        max_value=2,
        field_name="condicion_operacion.tipo",
    )
    gcond = _sub(dtip, "gCamCond")
    _sub(gcond, "iCondOpe", str(condicion))
    _sub(gcond, "dDCondOpe", "Contado" if condicion == 1 else "Crédito")
    if condicion == 1:
        _append_counted_payments(
            gcond=gcond,
            condicion_payload=condicion_payload,
            total=total,
            moneda=moneda,
            moneda_descripcion=moneda_descripcion,
            tipo_cambio=tipo_cambio,
        )
    else:
        _append_credit_payment(
            gcond=gcond,
            condicion_payload=condicion_payload,
            moneda=moneda,
            moneda_descripcion=moneda_descripcion,
        )


def _append_counted_payments(
    *,
    gcond: ET.Element,
    condicion_payload: dict,
    total: Decimal,
    moneda: str,
    moneda_descripcion: str,
    tipo_cambio: Decimal | None,
) -> None:
    forms = condicion_payload.get("formas_pago")
    if not isinstance(forms, list) or not forms:
        forms = [
            {
                "tipo": 1,
                "monto": _as_sifen_amount4(total),
                "moneda": moneda,
            }
        ]

    for form in forms:
        if not isinstance(form, dict):
            raise SifenValidationError(
                "documents.condicion_operacion.forma_pago_invalid"
            )
        payment_type = _resolve_code(
            _first_non_none(form, "tipo", "iTiPago"),
            mapping=_PAYMENT_TYPE_CODE_BY_NAME,
            default=1,
            min_value=1,
            max_value=99,
            field_name="condicion_operacion.formas_pago.tipo",
        )
        amount = _coerce_decimal(
            _first_non_none(form, "monto", "dMonTiPag"),
            field_name="condicion_operacion.formas_pago.monto",
            default=total,
            min_value=_ZERO,
        )
        payment_currency = (
            _clean_text(_first_non_none(form, "moneda", "cMoneTiPag")) or moneda
        ).upper()
        payment_currency_desc = _currency_description(
            _clean_text(_first_non_none(form, "moneda_descripcion", "dDMoneTiPag"))
            or moneda_descripcion
            if payment_currency == moneda
            else _currency_description(payment_currency)
        )

        pago = _sub(gcond, "gPaConEIni")
        _sub(pago, "iTiPago", str(payment_type))
        _sub(pago, "dDesTiPag", _payment_description(payment_type))
        _sub(pago, "dMonTiPag", _as_sifen_amount4(amount))
        _sub(pago, "cMoneTiPag", payment_currency)
        _sub(pago, "dDMoneTiPag", payment_currency_desc)
        payment_exchange = _coerce_decimal(
            _first_non_none(form, "tipo_cambio", "dTiCamTiPag"),
            field_name="condicion_operacion.formas_pago.tipo_cambio",
            default=tipo_cambio,
            min_value=Decimal("0.0001"),
        )
        if payment_currency != moneda and payment_exchange is not None:
            _sub(pago, "dTiCamTiPag", _as_sifen_amount4(payment_exchange))

        if payment_type == 2:
            cheque_number = _clean_text(
                _first_non_none(form, "numero_cheque", "dNumCheq")
            )
            bank = _clean_text(_first_non_none(form, "banco", "dBcoEmi"))
            if not cheque_number or not bank:
                raise SifenValidationError(
                    "documents.condicion_operacion.cheque_invalid"
                )
            gcheq = _sub(pago, "gPagCheq")
            _sub(gcheq, "dNumCheq", f"{int(cheque_number):08d}")
            _sub(gcheq, "dBcoEmi", bank)

        if payment_type in {3, 4}:
            _append_card_payment(pago=pago, form=form)


def _append_card_payment(*, pago: ET.Element, form: dict) -> None:
    card = form.get("tarjeta") if isinstance(form.get("tarjeta"), dict) else form
    brand_code = _resolve_code(
        _first_non_none(card, "marca", "iDenTarj"),
        mapping=_CARD_BRAND_CODE_BY_NAME,
        default=99,
        min_value=1,
        max_value=99,
        field_name="condicion_operacion.formas_pago.tarjeta.marca",
    )
    processing = _resolve_code(
        _first_non_none(card, "forma_procesamiento", "iForProPa"),
        mapping=_CARD_PROCESSING_CODE_BY_NAME,
        default=2,
        min_value=1,
        max_value=9,
        field_name="condicion_operacion.formas_pago.tarjeta.forma_procesamiento",
    )
    gtar = _sub(pago, "gPagTarCD")
    _sub(gtar, "iDenTarj", str(brand_code))
    _sub(gtar, "dDesDenTarj", _card_brand_description(brand_code))
    rs_pro = _clean_text(_first_non_none(card, "razon_social_procesadora", "dRSProTar"))
    if rs_pro:
        _sub(gtar, "dRSProTar", rs_pro)
    ruc_pro = _clean_text(_first_non_none(card, "ruc_procesadora", "dRUCProTar"))
    if ruc_pro:
        ruc_base, ruc_dv = _split_ruc_dv(
            {"ruc": ruc_pro, "dv": _clean_text(card.get("dv_procesadora"))}
        )
        _sub(gtar, "dRUCProTar", ruc_base)
        if ruc_dv:
            _sub(gtar, "dDVProTar", ruc_dv)
    _sub(gtar, "iForProPa", str(processing))
    code = _clean_text(_first_non_none(card, "codigo_autorizacion", "dCodAuOpe"))
    if code:
        _sub(gtar, "dCodAuOpe", str(int(code)))
    holder = _clean_text(_first_non_none(card, "nombre_titular", "dNomTit"))
    if holder:
        _sub(gtar, "dNomTit", holder)
    last4 = _clean_text(_first_non_none(card, "ultimos_4", "dNumTarj"))
    if last4:
        _sub(gtar, "dNumTarj", str(int(last4)))


def _append_credit_payment(
    *,
    gcond: ET.Element,
    condicion_payload: dict,
    moneda: str,
    moneda_descripcion: str,
) -> None:
    credit = (
        condicion_payload.get("credito")
        if isinstance(condicion_payload.get("credito"), dict)
        else condicion_payload
    )
    cond_cred = _resolve_code(
        _first_non_none(credit, "tipo", "iCondCred"),
        mapping={"plazo": 1, "cuotas": 2},
        default=1,
        min_value=1,
        max_value=2,
        field_name="condicion_operacion.credito.tipo",
    )
    gcred = _sub(gcond, "gPagCred")
    _sub(gcred, "iCondCred", str(cond_cred))
    _sub(gcred, "dDCondCred", "Plazo" if cond_cred == 1 else "Cuota")

    if cond_cred == 1:
        plazo = _clean_text(
            _first_non_none(credit, "descripcion", "plazo_descripcion", "dPlazoCre")
        )
        if not plazo:
            raise SifenValidationError(
                "documents.condicion_operacion.credito.plazo_required"
            )
        _sub(gcred, "dPlazoCre", plazo)
        return

    cuotas = credit.get("cuotas")
    if not isinstance(cuotas, list) or not cuotas:
        raise SifenValidationError(
            "documents.condicion_operacion.credito.cuotas_required"
        )
    _sub(gcred, "dCuotas", str(len(cuotas)))
    entrega = _coerce_decimal(
        _first_non_none(credit, "monto_entrega_inicial", "dMonEnt"),
        field_name="condicion_operacion.credito.monto_entrega_inicial",
        default=None,
        min_value=_ZERO,
    )
    if entrega is not None:
        _sub(gcred, "dMonEnt", _as_sifen_amount4(entrega))
    for cuota in cuotas:
        if not isinstance(cuota, dict):
            raise SifenValidationError(
                "documents.condicion_operacion.credito.cuota_invalid"
            )
        gcuota = _sub(gcred, "gCuotas")
        cuota_moneda = (
            _clean_text(_first_non_none(cuota, "moneda", "cMoneCuo")) or moneda
        ).upper()
        _sub(gcuota, "cMoneCuo", cuota_moneda)
        _sub(
            gcuota,
            "dDMoneCuo",
            _currency_description(cuota_moneda or moneda_descripcion),
        )
        cuota_monto = _coerce_decimal(
            _first_non_none(cuota, "monto", "dMonCuota"),
            field_name="condicion_operacion.credito.cuota.monto",
            default=None,
            required=True,
            min_value=Decimal("0.0001"),
        )
        _sub(gcuota, "dMonCuota", _as_sifen_amount4(cuota_monto))
        if cuota.get("fecha_vencimiento"):
            _sub(
                gcuota,
                "dVencCuo",
                _resolve_date(cuota["fecha_vencimiento"]).isoformat(),
            )


def _append_items(
    *,
    dtip: ET.Element | None,
    items: list[dict],
    moneda: str,
    condicion_tipo_cambio: int | None,
) -> list[_ItemComputation]:
    computations: list[_ItemComputation] = []
    for index, item in enumerate(items, start=1):
        qty = _coerce_decimal(
            _first_non_none(item, "cantidad", "dCantProSer"),
            field_name=f"items[{index}].cantidad",
            default=None,
            required=True,
            min_value=Decimal("0.00000001"),
        )
        unit_price = _coerce_decimal(
            _first_non_none(item, "precio_unitario", "precioUnitario", "dPUniProSer"),
            field_name=f"items[{index}].precio_unitario",
            default=None,
            required=True,
            min_value=_ZERO,
        )
        discount_particular = _coerce_decimal(
            _first_non_none(item, "descuento_particular", "dDescItem"),
            field_name=f"items[{index}].descuento_particular",
            default=_ZERO,
            min_value=_ZERO,
        )
        discount_global = _coerce_decimal(
            _first_non_none(item, "descuento_global", "dDescGloItem"),
            field_name=f"items[{index}].descuento_global",
            default=_ZERO,
            min_value=_ZERO,
        )
        anticipo_particular = _coerce_decimal(
            _first_non_none(item, "anticipo_particular", "dAntPreUniIt"),
            field_name=f"items[{index}].anticipo_particular",
            default=_ZERO,
            min_value=_ZERO,
        )
        anticipo_global = _coerce_decimal(
            _first_non_none(item, "anticipo_global", "dAntGloPreUniIt"),
            field_name=f"items[{index}].anticipo_global",
            default=_ZERO,
            min_value=_ZERO,
        )
        net_unit = (
            unit_price
            - discount_particular
            - discount_global
            - anticipo_particular
            - anticipo_global
        )
        if net_unit < _ZERO:
            raise SifenValidationError("documents.items.net_unit_negative")

        total_item = (net_unit * qty).quantize(_ITEM_TOTAL_Q, rounding=ROUND_HALF_UP)
        total_bruto = (unit_price * qty).quantize(_ITEM_TOTAL_Q, rounding=ROUND_HALF_UP)
        if total_item < _ZERO:
            raise SifenValidationError("documents.items.total_negative")

        affectation = _resolve_item_affectation(item)
        proportion = _resolve_item_proportion(item, affectation=affectation)
        rate = _resolve_item_rate(item, affectation=affectation)
        if affectation in {1, 4}:
            taxable = (
                total_item
                * (proportion / Decimal("100"))
                / (Decimal("1") + (Decimal(rate) / Decimal("100")))
            ).quantize(_ITEM_TOTAL_Q, rounding=ROUND_HALF_UP)
            iva = (taxable * (Decimal(rate) / Decimal("100"))).quantize(
                _ITEM_TOTAL_Q,
                rounding=ROUND_HALF_UP,
            )
            base_exe = _ZERO
        else:
            taxable = _ZERO
            iva = _ZERO
            base_exe = total_item
        taxable = _quantize_tax_value(taxable, moneda=moneda)
        iva = _quantize_tax_value(iva, moneda=moneda)
        base_exe = _quantize_tax_value(base_exe, moneda=moneda)
        rate_item = None
        total_item_gs = None
        if moneda != "PYG" and condicion_tipo_cambio == 2:
            rate_item = _coerce_decimal(
                _first_non_none(item, "tipo_cambio_item", "dTiCamIt"),
                field_name=f"items[{index}].tipo_cambio_item",
                default=None,
                required=True,
                min_value=Decimal("0.0001"),
            )
            total_item_gs = _quantize_guarani_value(total_item * rate_item)

        if dtip is not None:
            current = _sub(dtip, "gCamItem")
            _sub(
                current,
                "dCodInt",
                _clean_text(_first_non_none(item, "codigo_interno", "codigo"))
                or f"ITEM{index:03d}",
            )
            _sub(
                current,
                "dDesProSer",
                _clean_text(_first_non_none(item, "descripcion", "dDesProSer"))
                or f"Ítem {index}",
            )
            _sub(
                current,
                "cUniMed",
                str(
                    int(
                        _clean_text(
                            _first_non_none(
                                item, "unidad_medida", "codigoUnidad", "cUniMed"
                            )
                        )
                        or "77"
                    )
                ),
            )
            _sub(
                current,
                "dDesUniMed",
                _clean_text(
                    _first_non_none(item, "descripcion_unidad", "unidad", "dDesUniMed")
                )
                or "UNI",
            )
            _sub(current, "dCantProSer", _as_sifen_quantity(qty))
            cdc_anticipo = _clean_text(
                _first_non_none(item, "cdc_anticipo", "dCDCAnticipo")
            )
            if cdc_anticipo:
                _sub(current, "dCDCAnticipo", cdc_anticipo)

            values = _sub(current, "gValorItem")
            _sub(values, "dPUniProSer", _as_sifen_amount(unit_price))
            if rate_item is not None:
                _sub(values, "dTiCamIt", _as_sifen_amount4(rate_item))
            _sub(values, "dTotBruOpeItem", _as_sifen_amount(total_bruto))

            rests = _sub(values, "gValorRestaItem")
            _sub(rests, "dDescItem", _as_sifen_amount(discount_particular))
            discount_percentage = _coerce_decimal(
                _first_non_none(item, "porcentaje_descuento_particular", "dPorcDesIt"),
                field_name=f"items[{index}].porcentaje_descuento_particular",
                default=None,
                min_value=_ZERO,
            )
            if (
                discount_percentage is None
                and unit_price > _ZERO
                and discount_particular > _ZERO
            ):
                discount_percentage = (
                    (discount_particular / unit_price) * Decimal("100")
                ).quantize(_PERCENT_Q, rounding=ROUND_HALF_UP)
            if discount_percentage is not None:
                _sub(rests, "dPorcDesIt", _as_sifen_percent(discount_percentage))
            _sub(rests, "dDescGloItem", _as_sifen_amount(discount_global))
            _sub(rests, "dAntPreUniIt", _as_sifen_amount(anticipo_particular))
            _sub(rests, "dAntGloPreUniIt", _as_sifen_amount(anticipo_global))
            _sub(rests, "dTotOpeItem", _as_sifen_amount(total_item))
            if total_item_gs is not None:
                _sub(rests, "dTotOpeGs", _as_sifen_amount(total_item_gs))

            iva_node = _sub(current, "gCamIVA")
            _sub(iva_node, "iAfecIVA", str(affectation))
            _sub(iva_node, "dDesAfecIVA", _affectation_description(affectation))
            _sub(iva_node, "dPropIVA", _as_sifen_percent(proportion))
            _sub(iva_node, "dTasaIVA", str(rate))
            _sub(iva_node, "dBasGravIVA", _as_sifen_amount(taxable))
            _sub(iva_node, "dLiqIVAItem", _as_sifen_amount(iva))
            _sub(iva_node, "dBasExe", _as_sifen_amount(base_exe))

        computations.append(
            _ItemComputation(
                amount_exe=total_item if affectation == 3 else _ZERO,
                amount_exo=total_item if affectation == 2 else _ZERO,
                amount_5=total_item if rate == 5 else _ZERO,
                amount_10=total_item if rate == 10 else _ZERO,
                discount_particular=(discount_particular * qty).quantize(
                    _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
                ),
                discount_global=(discount_global * qty).quantize(
                    _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
                ),
                anticipo_particular=(anticipo_particular * qty).quantize(
                    _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
                ),
                anticipo_global=(anticipo_global * qty).quantize(
                    _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
                ),
                base_5=taxable if rate == 5 else _ZERO,
                base_10=taxable if rate == 10 else _ZERO,
                iva_5=iva if rate == 5 else _ZERO,
                iva_10=iva if rate == 10 else _ZERO,
                total_gs=total_item_gs,
            )
        )
    return computations


def _calculate_totals(
    item_computations: list[_ItemComputation], *, moneda: str
) -> _Totals:
    sub_exe = sum((x.amount_exe for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    sub_exo = sum((x.amount_exo for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    sub_5 = sum((x.amount_5 for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    sub_10 = sum((x.amount_10 for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    total = (sub_exe + sub_exo + sub_5 + sub_10).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    total_discount_particular = sum(
        (x.discount_particular for x in item_computations), _ZERO
    ).quantize(
        _ITEM_TOTAL_Q,
        rounding=ROUND_HALF_UP,
    )
    total_discount_global = sum(
        (x.discount_global for x in item_computations), _ZERO
    ).quantize(
        _ITEM_TOTAL_Q,
        rounding=ROUND_HALF_UP,
    )
    total_anticipo_particular = sum(
        (x.anticipo_particular for x in item_computations), _ZERO
    ).quantize(
        _ITEM_TOTAL_Q,
        rounding=ROUND_HALF_UP,
    )
    total_anticipo_global = sum(
        (x.anticipo_global for x in item_computations), _ZERO
    ).quantize(
        _ITEM_TOTAL_Q,
        rounding=ROUND_HALF_UP,
    )
    base_5 = sum((x.base_5 for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    base_10 = sum((x.base_10 for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    iva_5 = sum((x.iva_5 for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    iva_10 = sum((x.iva_10 for x in item_computations), _ZERO).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    base_5 = _quantize_tax_value(base_5, moneda=moneda)
    base_10 = _quantize_tax_value(base_10, moneda=moneda)
    iva_5 = _quantize_tax_value(iva_5, moneda=moneda)
    iva_10 = _quantize_tax_value(iva_10, moneda=moneda)
    redondeo = _calculate_rounding(total=total, moneda=moneda)
    total_neto = (total - redondeo).quantize(_ITEM_TOTAL_Q, rounding=ROUND_HALF_UP)
    total_iva = (iva_5 + iva_10).quantize(_ITEM_TOTAL_Q, rounding=ROUND_HALF_UP)
    total_iva = _quantize_tax_value(total_iva, moneda=moneda)
    return _Totals(
        sub_exe=sub_exe,
        sub_exo=sub_exo,
        sub_5=sub_5,
        sub_10=sub_10,
        total=total,
        total_discount_particular=total_discount_particular,
        total_discount_global=total_discount_global,
        total_anticipo_particular=total_anticipo_particular,
        total_anticipo_global=total_anticipo_global,
        base_5=base_5,
        base_10=base_10,
        iva_5=iva_5,
        iva_10=iva_10,
        redondeo=redondeo,
        total_neto=total_neto,
        total_iva=total_iva,
        total_gs=None,
    )


def _append_totals(de: ET.Element, totals: _Totals) -> None:
    gtot = _sub(de, "gTotSub")
    _sub_optional_amount(gtot, "dSubExe", totals.sub_exe)
    _sub_optional_amount(gtot, "dSubExo", totals.sub_exo)
    _sub_optional_amount(gtot, "dSub5", totals.sub_5)
    _sub_optional_amount(gtot, "dSub10", totals.sub_10)
    _sub(gtot, "dTotOpe", _as_sifen_amount(totals.total))
    _sub(gtot, "dTotDesc", _as_sifen_amount(totals.total_discount_particular))
    _sub(gtot, "dTotDescGlotem", _as_sifen_amount(totals.total_discount_global))
    _sub(gtot, "dTotAntItem", _as_sifen_amount(totals.total_anticipo_particular))
    _sub(gtot, "dTotAnt", _as_sifen_amount(totals.total_anticipo_global))
    discount_total = (
        totals.total_discount_particular + totals.total_discount_global
    ).quantize(
        _ITEM_TOTAL_Q,
        rounding=ROUND_HALF_UP,
    )
    if totals.total > _ZERO:
        pct = ((discount_total / totals.total) * Decimal("100")).quantize(
            _PERCENT_Q, rounding=ROUND_HALF_UP
        )
    else:
        pct = _ZERO
    _sub(gtot, "dPorcDescTotal", _as_sifen_percent(pct))
    _sub(gtot, "dDescTotal", _as_sifen_amount(discount_total))
    _sub(
        gtot,
        "dAnticipo",
        _as_sifen_amount(
            (totals.total_anticipo_particular + totals.total_anticipo_global)
        ),
    )
    _sub(gtot, "dRedon", _as_sifen_amount4(totals.redondeo))
    _sub_optional_amount(gtot, "dComi", _ZERO)
    _sub(gtot, "dTotGralOpe", _as_sifen_amount(totals.total_neto))
    _sub_optional_amount(gtot, "dIVA5", totals.iva_5)
    _sub_optional_amount(gtot, "dIVA10", totals.iva_10)
    _sub_optional_amount(gtot, "dIVAComi", _ZERO)
    _sub_optional_amount(gtot, "dTotIVA", totals.total_iva)
    _sub_optional_amount(gtot, "dBaseGrav5", totals.base_5)
    _sub_optional_amount(gtot, "dBaseGrav10", totals.base_10)
    _sub_optional_amount(gtot, "dTBasGraIVA", totals.base_5 + totals.base_10)
    if totals.total_gs is not None:
        _sub(gtot, "dTotalGs", _as_sifen_amount(totals.total_gs))


def _resolve_total_gs(
    *,
    totals: _Totals,
    item_computations: list[_ItemComputation],
    moneda: str,
    condicion_tipo_cambio: int | None,
    tipo_cambio: Decimal | None,
) -> Decimal | None:
    if moneda == "PYG":
        return None
    if condicion_tipo_cambio == 1 and tipo_cambio is not None:
        return _quantize_guarani_value(totals.total_neto * tipo_cambio)
    if condicion_tipo_cambio == 2:
        total_item_gs = sum(
            (item.total_gs or _ZERO for item in item_computations),
            _ZERO,
        )
        return _quantize_guarani_value(total_item_gs)
    return None


def _quantize_tax_value(value: Decimal, *, moneda: str) -> Decimal:
    if moneda == "PYG":
        return _quantize_guarani_value(value)
    return value.quantize(_ITEM_TOTAL_Q, rounding=ROUND_HALF_UP)


def _quantize_guarani_value(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _sub_optional_amount(parent: ET.Element, name: str, value: Decimal) -> None:
    if value == _ZERO:
        return
    _sub(parent, name, _as_sifen_amount(value))


def _append_associated_documents_if_any(*, de: ET.Element, typed_payload: dict) -> None:
    asociado = typed_payload.get("documento_asociado")
    if asociado is None:
        return
    if isinstance(asociado, list):
        for current in asociado:
            if isinstance(current, dict):
                _append_associated_document(de=de, asociado=current, required=False)
        return
    if isinstance(asociado, dict):
        _append_associated_document(de=de, asociado=asociado, required=False)


def _append_outside_signature_group(*, root: ET.Element, dcarqr: str) -> None:
    gcam = _sub(root, "gCamFuFD")
    _sub(gcam, "dCarQR", dcarqr)


def _append_associated_document(
    *, de: ET.Element, asociado: dict, required: bool
) -> None:
    tipo = _resolve_code(
        _first_non_none(asociado, "tipo", "iTipDocAso"),
        mapping={"electronico": 1, "impreso": 2, "constancia_electronica": 3},
        default=1,
        min_value=1,
        max_value=3,
        field_name="documento_asociado.tipo",
    )
    asoc = _sub(de, "gCamDEAsoc")
    _sub(asoc, "iTipDocAso", str(tipo))
    _sub(asoc, "dDesTipDocAso", _associated_doc_type_description(tipo))

    if tipo == 1:
        cdc_ref = _clean_text(_first_non_none(asociado, "cdc", "dCdCDERef"))
        if not cdc_ref:
            if required:
                raise SifenValidationError(
                    "nota_credito.documento_asociado.cdc_required"
                )
            return
        _sub(asoc, "dCdCDERef", cdc_ref)
        return

    if tipo == 2:
        timbrado = _clean_text(_first_non_none(asociado, "timbrado", "dNTimDI"))
        est = _clean_text(_first_non_none(asociado, "establecimiento", "dEstDocAso"))
        point = _clean_text(_first_non_none(asociado, "punto", "dPExpDocAso"))
        number = _clean_text(_first_non_none(asociado, "numero", "dNumDocAso"))
        issued_on = _first_non_none(asociado, "fecha_emision", "fecha", "dFecEmiDI")
        if not timbrado or not est or not point or not number or issued_on is None:
            raise SifenValidationError(
                "nota_credito.documento_asociado.impreso_invalid"
            )
        tipo_impreso = _resolve_code(
            _first_non_none(asociado, "tipo_documento_impreso", "iTipoDocAso"),
            mapping={},
            default=1,
            min_value=1,
            max_value=4,
            field_name="documento_asociado.tipo_documento_impreso",
        )
        _sub(asoc, "dNTimDI", str(int(timbrado)))
        _sub(asoc, "dEstDocAso", f"{int(est):03d}")
        _sub(asoc, "dPExpDocAso", f"{int(point):03d}")
        _sub(asoc, "dNumDocAso", f"{int(number):07d}")
        _sub(asoc, "iTipoDocAso", str(tipo_impreso))
        _sub(asoc, "dDTipoDocAso", _printed_doc_type_description(tipo_impreso))
        _sub(asoc, "dFecEmiDI", _resolve_date(issued_on).isoformat())
        return

    # Constancia electrónica
    tipo_constancia = _resolve_code(
        _first_non_none(asociado, "tipo_constancia", "iTipCons"),
        mapping={},
        default=1,
        min_value=1,
        max_value=2,
        field_name="documento_asociado.tipo_constancia",
    )
    numero_constancia = _clean_text(
        _first_non_none(asociado, "numero_constancia", "dNumCons")
    )
    numero_control = _clean_text(
        _first_non_none(asociado, "numero_control", "dNumControl")
    )
    if not numero_constancia or not numero_control:
        raise SifenValidationError("nota_credito.documento_asociado.constancia_invalid")
    _sub(asoc, "iTipCons", str(tipo_constancia))
    _sub(
        asoc,
        "dDesTipCons",
        "Constancia de no ser contribuyente"
        if tipo_constancia == 1
        else "Constancia de microproductores",
    )
    _sub(asoc, "dNumCons", numero_constancia)
    _sub(asoc, "dNumControl", numero_control)


def _resolve_dcarqr_value(
    *,
    typed_payload: dict,
    doc_id: str,
    fecha_emision: str,
    receptor: str,
    total_neto: Decimal,
    total_iva: Decimal,
    items_count: int,
) -> str:
    provided = _clean_text(_first_non_none(typed_payload, "dCarQR", "dcarqr", "qr_url"))
    if provided:
        if len(provided) < 100 or len(provided) > 600:
            raise SifenValidationError("documents.qr.length_invalid")
        return provided

    compact_date = (fecha_emision.replace("-", "").replace(":", "").replace("T", ""))[
        :14
    ]
    payload = (
        "https://ekuatia.set.gov.py/consultas-test/qr?"
        f"nVersion=150&Id={doc_id}&dFeEmiDE={compact_date}"
        f"&dRucRec={receptor}&dTotGralOpe={_as_sifen_amount(total_neto)}"
        f"&dTotIVA={_as_sifen_amount(total_iva)}&cItems={items_count}"
        "&DigestValue=0&IdCSC=0001&cHashQR=0"
    )
    if len(payload) < 100:
        payload = f"{payload}&pad={'0' * (100 - len(payload))}"
    if len(payload) > 600:
        payload = payload[:600]
    return payload


def _resolve_qr_receptor(cliente: dict) -> str:
    ruc = _clean_text(cliente.get("ruc"))
    if ruc:
        return ruc.replace("-", "")
    doc = _clean_text(
        _first_non_none(
            cliente,
            "numero_documento_identidad",
            "numero_documento",
            "dNumIDRec",
        )
    )
    return doc or "0"


def _build_doc_id(
    *,
    i_tide: int,
    issuer: _Issuer,
    fecha_emision: str,
    establecimiento: str,
    punto: str,
    numero_documento: int,
    codigo_seguridad: str,
) -> str:
    # The CDC takes RUC, DV and iTipCont from the same source as gEmis (1000).
    return generate_cdc(
        i_tide=i_tide,
        d_ruc_em=issuer.ruc,
        d_dv_emi=issuer.dv,
        d_est=establecimiento,
        d_pun_exp=punto,
        d_num_doc=str(numero_documento),
        i_tip_cont=str(issuer.profile.taxpayer_type),
        d_fe_emi_de=fecha_emision,
        i_tip_emi="1",
        d_cod_seg=codigo_seguridad,
    )


def _required_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise SifenValidationError("items must include at least one item")
    normalized = [item for item in items if isinstance(item, dict)]
    if not normalized:
        raise SifenValidationError("items must include at least one valid item object")
    return normalized


def _required_object(payload: dict, key: str) -> dict:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise SifenValidationError(f"{key} is required")
    return value


def _required_intlike(payload: dict, key: str, default: int | None = None) -> int:
    value = payload.get(key)
    if value is None:
        if default is not None:
            return default
        raise SifenValidationError(f"{key} is required")
    try:
        return int(str(value))
    except ValueError as exc:
        raise SifenValidationError(f"{key} must be an integer") from exc


def _resolve_code(
    value,
    *,
    mapping: dict[str, int],
    default: int,
    min_value: int,
    max_value: int,
    field_name: str,
) -> int:
    if value is None:
        resolved = default
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            resolved = default
        elif stripped.isdigit():
            resolved = int(stripped)
        else:
            key = stripped.lower().replace(" ", "_").replace("-", "_")
            resolved = mapping.get(key)
            if resolved is None:
                raise SifenValidationError(f"{field_name} is invalid")
    else:
        try:
            resolved = int(value)
        except (TypeError, ValueError) as exc:
            raise SifenValidationError(f"{field_name} is invalid") from exc
    if resolved < min_value or resolved > max_value:
        raise SifenValidationError(f"{field_name} is out of range")
    return resolved


def _resolve_currency_data(
    typed_payload: dict,
) -> tuple[str, str, int | None, Decimal | None]:
    moneda = (_clean_text(typed_payload.get("moneda")) or "PYG").upper()
    condicion_tipo_cambio = _coerce_int(
        typed_payload.get("condicion_tipo_cambio"),
        field_name="condicion_tipo_cambio",
        default=None,
        min_value=1,
        max_value=2,
    )
    tipo_cambio = _coerce_decimal(
        typed_payload.get("tipo_cambio"),
        field_name="tipo_cambio",
        default=None,
        min_value=Decimal("0.0001"),
    )
    return moneda, _currency_description(moneda), condicion_tipo_cambio, tipo_cambio


def _resolve_condition_payload(typed_payload: dict) -> dict:
    condition = typed_payload.get("condicion_operacion")
    if isinstance(condition, dict):
        return condition
    legacy = typed_payload.get("condicion")
    if isinstance(legacy, dict):
        return legacy
    return {}


def _resolve_item_affectation(item: dict) -> int:
    if item.get("afectacion") is None and item.get("iAfecIVA") is None:
        legacy_rate = _coerce_int(
            _first_non_none(item, "iva", "tasa", "dTasaIVA"),
            field_name="items.iva",
            default=10,
            min_value=0,
            max_value=10,
        )
        if legacy_rate in {5, 10}:
            return 1
        return 3
    return _resolve_code(
        _first_non_none(item, "afectacion", "iAfecIVA"),
        mapping=_AFFECTATION_CODE_BY_NAME,
        default=1,
        min_value=1,
        max_value=4,
        field_name="items.afectacion",
    )


def _resolve_item_proportion(item: dict, *, affectation: int) -> Decimal:
    proportion = _coerce_decimal(
        _first_non_none(item, "proporcion_gravada", "dPropIVA"),
        field_name="items.proporcion_gravada",
        default=Decimal("100"),
        min_value=_ZERO,
    )
    if affectation != 4:
        return Decimal("100")
    if proportion <= _ZERO or proportion > Decimal("100"):
        raise SifenValidationError("items.proporcion_gravada must be between 0 and 100")
    return proportion


def _resolve_item_rate(item: dict, *, affectation: int) -> int:
    rate = _coerce_int(
        _first_non_none(item, "tasa", "iva", "dTasaIVA"),
        field_name="items.tasa",
        default=10 if affectation in {1, 4} else 0,
        min_value=0,
        max_value=10,
    )
    if affectation in {2, 3}:
        return 0
    if rate not in {5, 10}:
        raise SifenValidationError("items.tasa must be 5 or 10 for taxable IVA items")
    return rate


def _resolve_emission_datetime(payload: dict) -> str:
    raw = _first_non_none(payload, "fecha_emision", "fecha")
    if raw is None:
        return format_sifen_datetime(paraguay_now())
    try:
        return parse_sifen_datetime(raw).isoformat()
    except ValueError as exc:
        raise SifenValidationError("fecha/fecha_emision has invalid format") from exc


def _resolve_date(raw) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    value = str(raw or "").strip()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SifenValidationError("invalid date format") from exc


def _split_ruc_dv(cliente: dict) -> tuple[str, str | None]:
    ruc = _clean_text(cliente.get("ruc"))
    if not ruc:
        raise SifenValidationError("cliente.ruc is required")
    if "-" in ruc:
        base, dv = ruc.split("-", 1)
        return base.strip(), dv.strip()
    dv = _clean_text(cliente.get("dv")) or None
    return ruc, dv


def _normalize_three_digits(value, fallback: str) -> str:
    if value is None:
        value = fallback
    return f"{int(str(value)):03d}"


def _resolve_security_code(
    persisted: str | None, typed_payload: dict, numero_documento: int
) -> str:
    """dCodSeg persisted at creation (MT v150 §10.3); never a constant."""

    raw = persisted or typed_payload.get("codigo_seguridad")
    if raw is None:
        raise SifenValidationError("documents.codigo_seguridad.missing")
    try:
        return normalize_security_code(raw, document_number=numero_documento)
    except InvalidSecurityCodeError as exc:
        raise SifenValidationError(exc.code) from exc








def _transaction_description(code: int) -> str:
    return _TRANSACTION_DESCRIPTION_BY_CODE.get(
        code, _TRANSACTION_DESCRIPTION_BY_CODE[1]
    )


def _tax_description(code: int) -> str:
    return _TAX_DESCRIPTION_BY_CODE.get(code, _TAX_DESCRIPTION_BY_CODE[1])


def _presence_description(code: int) -> str:
    return _PRESENCE_DESCRIPTION_BY_CODE.get(code, _PRESENCE_DESCRIPTION_BY_CODE[1])


def _affectation_description(code: int) -> str:
    return _AFFECTATION_DESCRIPTION_BY_CODE.get(
        code, _AFFECTATION_DESCRIPTION_BY_CODE[1]
    )


def _payment_description(code: int) -> str:
    return _PAYMENT_DESCRIPTION_BY_TYPE.get(code, _PAYMENT_DESCRIPTION_BY_TYPE[99])


def _card_brand_description(code: int) -> str:
    return _CARD_BRAND_DESCRIPTION_BY_CODE.get(
        code, _CARD_BRAND_DESCRIPTION_BY_CODE[99]
    )


def _nota_credito_motive_description(code: int) -> str:
    return _MOTIVE_DESCRIPTION_BY_CODE.get(code, _MOTIVE_DESCRIPTION_BY_CODE[1])


def _associated_doc_type_description(code: int) -> str:
    return _ASSOCIATED_DOC_TYPE_DESCRIPTION.get(
        code, _ASSOCIATED_DOC_TYPE_DESCRIPTION[1]
    )


def _printed_doc_type_description(code: int) -> str:
    return _PRINTED_DOC_TYPE_DESCRIPTION.get(code, _PRINTED_DOC_TYPE_DESCRIPTION[1])


def _currency_description(code: str) -> str:
    currency = code.upper()
    known = {
        "PYG": "Guarani",
        "USD": "Dólar",
        "EUR": "Euro",
        "BRL": "Real",
        "ARS": "Peso argentino",
    }
    return known.get(currency, currency)


def _calculate_rounding(*, total: Decimal, moneda: str) -> Decimal:
    if total <= _ZERO:
        return _ZERO
    if moneda == "PYG":
        divisor = Decimal("50")
    else:
        divisor = Decimal("0.50")
    redondeo = (total % divisor).quantize(_AMOUNT4_Q, rounding=ROUND_HALF_UP)
    return redondeo


def _assert_totals_consistency(totals: _Totals) -> None:
    expected_total = (
        totals.sub_exe + totals.sub_exo + totals.sub_5 + totals.sub_10
    ).quantize(
        _ITEM_TOTAL_Q,
        rounding=ROUND_HALF_UP,
    )
    expected_iva = (totals.iva_5 + totals.iva_10).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    expected_base = (totals.base_5 + totals.base_10).quantize(
        _ITEM_TOTAL_Q, rounding=ROUND_HALF_UP
    )
    if totals.total != expected_total:
        raise SifenValidationError("documents.totals.mismatch")
    if totals.total_iva != expected_iva:
        raise SifenValidationError("documents.totals.mismatch")
    if expected_base < _ZERO:
        raise SifenValidationError("documents.totals.mismatch")


def _finalize_xml(root: ET.Element) -> str:
    xml_bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    xml_text = xml_bytes.decode("UTF-8")
    if _has_ds_namespace_prefix(xml_text):
        raise SifenValidationError("documents.signature.namespace_prefix_not_allowed")
    if "<!--" in xml_text:
        raise SifenValidationError("documents.xml.comments_not_allowed")
    _assert_no_field_boundary_whitespace(root)
    errors = validate_xml(xml_text)
    filtered_errors = []
    for error in errors:
        if "{http://www.w3.org/2000/09/xmldsig#}Signature" in error:
            continue
        # Known defect in DE_v150.xsd: tgCompPub defines "dEntCont " (trailing space).
        # XML names cannot contain trailing spaces, so valid "dEntCont" instances are
        # rejected by this broken schema token.
        if "Expected is ( {http://ekuatia.set.gov.py/sifen/xsd}dEntCont  )" in error:
            continue
        filtered_errors.append(error)
    if filtered_errors:
        raise SifenValidationError(f"documents.xml.invalid_schema:{filtered_errors[0]}")
    return xml_text


def _has_ds_namespace_prefix(xml_text: str) -> bool:
    """Tell whether the XML uses a ``ds:`` element or declares that prefix.

    Only markup counts: text content is escaped by the serializer, so a
    description such as ``"Brands: X"`` never matches.
    """

    return _DS_PREFIX_PATTERN.search(xml_text) is not None


def _assert_no_field_boundary_whitespace(root: ET.Element) -> None:
    for element in root.iter():
        if element.text is None:
            continue
        if element.text != element.text.strip():
            raise SifenValidationError("documents.xml.invalid_field_whitespace")
        if any(char in element.text for char in ("\n", "\r", "\t")):
            raise SifenValidationError("documents.xml.invalid_field_whitespace")


def _find_de(root: ET.Element) -> ET.Element:
    de = root.find(_tag("DE"))
    if de is None:
        raise SifenValidationError("DE node missing while building typed XML")
    return de


def _coerce_int(
    value,
    *,
    field_name: str,
    default: int | None = None,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int | None:
    if value is None:
        parsed = default
    else:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError) as exc:
            raise SifenValidationError(f"{field_name} must be an integer") from exc
    if parsed is None:
        return None
    if min_value is not None and parsed < min_value:
        raise SifenValidationError(f"{field_name} is out of range")
    if max_value is not None and parsed > max_value:
        raise SifenValidationError(f"{field_name} is out of range")
    return parsed


def _coerce_decimal(
    value,
    *,
    field_name: str,
    default: Decimal | None = None,
    required: bool = False,
    min_value: Decimal | None = None,
) -> Decimal | None:
    if value is None:
        parsed = default
    else:
        try:
            parsed = Decimal(str(value))
        except Exception as exc:  # pragma: no cover - Decimal message branch
            raise SifenValidationError(f"{field_name} must be numeric") from exc
    if parsed is None and required:
        raise SifenValidationError(f"{field_name} is required")
    if parsed is None:
        return None
    if min_value is not None and parsed < min_value:
        raise SifenValidationError(f"{field_name} is out of range")
    return parsed


def _clean_text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _first_non_none(data: dict, *keys: str):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _as_sifen_quantity(value: Decimal) -> str:
    return _as_sifen_decimal(value, quantizer=_AMOUNT_Q)


def _as_sifen_percent(value: Decimal) -> str:
    return _as_sifen_decimal(value, quantizer=_PERCENT_Q)


def _as_sifen_amount(value: Decimal) -> str:
    return _as_sifen_decimal(value, quantizer=_AMOUNT_Q)


def _as_sifen_amount4(value: Decimal) -> str:
    return _as_sifen_decimal(value, quantizer=_AMOUNT4_Q)


def _as_sifen_decimal(value: Decimal, *, quantizer: Decimal) -> str:
    quantized = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _tag(name: str) -> str:
    return f"{{{SIFEN_NS}}}{name}"


def _sub(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
    child = ET.SubElement(parent, _tag(name))
    if text is not None:
        child.text = text
    return child
