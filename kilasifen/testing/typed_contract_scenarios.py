"""Reusable typed contract scenarios for Factura/Nota de Credito tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TypedContractScenario:
    """One deterministic typed contract scenario."""

    name: str
    document_type: str
    contract: str
    payload: dict


def get_typed_contract_scenarios() -> list[TypedContractScenario]:
    """Return deterministic scenarios used by golden and API integration tests."""

    scenarios = [
        TypedContractScenario(
            name="factura_b2b_iva10",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "tipo_transaccion": "venta_mercaderia",
                "tipo_impuesto": "iva",
                "indicador_presencia": "presencial",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {"tipo": "efectivo", "monto": "100000", "moneda": "PYG"}
                    ],
                },
                "items": [
                    {
                        "codigo_interno": "A-001",
                        "descripcion": "Producto IVA 10",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "100000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="factura_b2c_iva_mixto",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "tipo_transaccion": "venta_mercaderia",
                "tipo_impuesto": "iva",
                "indicador_presencia": "electronica",
                "cliente": {
                    "naturaleza": 2,
                    "tipo_operacion": 2,
                    "tipo_documento_identidad": 5,
                    "numero_documento_identidad": "0",
                    "nombre": "CONSUMIDOR FINAL",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {"tipo": "efectivo", "monto": "170000", "moneda": "PYG"}
                    ],
                },
                "items": [
                    {
                        "codigo_interno": "MIX-10",
                        "descripcion": "Item IVA 10",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "100000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    },
                    {
                        "codigo_interno": "MIX-05",
                        "descripcion": "Item IVA 5",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "50000",
                        "afectacion": "gravado",
                        "tasa": 5,
                    },
                    {
                        "codigo_interno": "MIX-EX",
                        "descripcion": "Item exento",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "20000",
                        "afectacion": "exento",
                        "tasa": 0,
                    },
                ],
            },
        ),
        TypedContractScenario(
            name="factura_descuento_global",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "items": [
                    {
                        "codigo_interno": "DG-1",
                        "descripcion": "Servicio A",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "90000",
                        "descuento_global": "5000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    },
                    {
                        "codigo_interno": "DG-2",
                        "descripcion": "Servicio B",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "70000",
                        "descuento_global": "5000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    },
                ],
            },
        ),
        TypedContractScenario(
            name="factura_anticipo",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "items": [
                    {
                        "codigo_interno": "AN-1",
                        "descripcion": "Producto con anticipo",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "120000",
                        "anticipo_particular": "20000",
                        "cdc_anticipo": "01800123450001001000000012026010112345678901",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="factura_credito_cuotas",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "condicion_operacion": {
                    "tipo": "credito",
                    "credito": {
                        "tipo": "cuotas",
                        "monto_entrega_inicial": "10000",
                        "cuotas": [
                            {
                                "monto": "30000",
                                "fecha_vencimiento": "2026-05-10",
                                "moneda": "PYG",
                            },
                            {
                                "monto": "30000",
                                "fecha_vencimiento": "2026-06-10",
                                "moneda": "PYG",
                            },
                            {
                                "monto": "30000",
                                "fecha_vencimiento": "2026-07-10",
                                "moneda": "PYG",
                            },
                        ],
                    },
                },
                "items": [
                    {
                        "codigo_interno": "CR-1",
                        "descripcion": "Servicio a credito",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "100000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="factura_pago_tarjeta",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {
                            "tipo": "tarjeta_credito",
                            "monto": "150000",
                            "moneda": "PYG",
                            "tarjeta": {
                                "marca": "visa",
                                "razon_social_procesadora": "PROC SA",
                                "ruc_procesadora": "80010000-1",
                                "forma_procesamiento": "pos",
                                "codigo_autorizacion": "123456",
                                "nombre_titular": "ANA PEREZ",
                                "ultimos_4": "1234",
                            },
                        }
                    ],
                },
                "items": [
                    {
                        "codigo_interno": "TJ-1",
                        "descripcion": "Venta tarjeta",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "150000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="factura_pago_cheque",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {
                            "tipo": "cheque",
                            "monto": "95000",
                            "moneda": "PYG",
                            "numero_cheque": "12345678",
                            "banco": "BASA",
                        }
                    ],
                },
                "items": [
                    {
                        "codigo_interno": "CH-1",
                        "descripcion": "Venta cheque",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "95000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="factura_moneda_usd",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "moneda": "USD",
                "condicion_tipo_cambio": 1,
                "tipo_cambio": "7300.0000",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {"tipo": "transferencia", "monto": "120.50", "moneda": "USD"}
                    ],
                },
                "items": [
                    {
                        "codigo_interno": "USD-1",
                        "descripcion": "Venta USD",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "120.50",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="factura_b2g",
            document_type="factura",
            contract="factura_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 3,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "MINISTERIO TEST",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                    "compras_publicas": {
                        "modalidad": "1",
                        "entidad": "12345",
                        "anio": "24",
                        "secuencia": "123",
                        "fecha_codigo": "2026-04-01",
                    },
                },
                "items": [
                    {
                        "codigo_interno": "B2G-1",
                        "descripcion": "Servicio gobierno",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "200000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="nc_total",
            document_type="nota_credito",
            contract="nota_credito_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "motivo_emision": "devolucion_y_ajuste",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "documento_asociado": {
                    "tipo": 1,
                    "cdc": "01800123450001001000000012026010112345678901",
                },
                "items": [
                    {
                        "codigo_interno": "NC-TOTAL-1",
                        "descripcion": "NC total",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "100000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="nc_parcial",
            document_type="nota_credito",
            contract="nota_credito_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "motivo_emision": "devolucion",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "documento_asociado": {
                    "tipo": 1,
                    "cdc": "01800123450001001000000012026010112345678901",
                },
                "items": [
                    {
                        "codigo_interno": "NC-P-1",
                        "descripcion": "Item parcial A",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "30000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    },
                    {
                        "codigo_interno": "NC-P-2",
                        "descripcion": "Item parcial B",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "20000",
                        "afectacion": "gravado",
                        "tasa": 5,
                    },
                ],
            },
        ),
        TypedContractScenario(
            name="nc_motivo_descuento",
            document_type="nota_credito",
            contract="nota_credito_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "motivo_emision": "descuento",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "documento_asociado": {
                    "tipo": 1,
                    "cdc": "01800123450001001000000012026010112345678901",
                },
                "items": [
                    {
                        "codigo_interno": "NC-DESC-1",
                        "descripcion": "Descuento posterior",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "25000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
        TypedContractScenario(
            name="nd_recupero_costo",
            document_type="nota_debito",
            contract="nota_debito_v1",
            payload={
                "numero": 1,
                "establecimiento": "001",
                "punto": "001",
                "fecha_emision": "2026-04-25T10:00:00",
                "motivo_emision": "recupero_costo",
                "cliente": {
                    "naturaleza": 1,
                    "tipo_operacion": 1,
                    "tipo_contribuyente": 2,
                    "ruc": "80069563-1",
                    "razon_social": "TIPS SA",
                    "direccion": "ASUNCION",
                    "numero_casa": "123",
                },
                "documento_asociado": {
                    "tipo": 1,
                    "cdc": "01800123450001001000000012026010112345678901",
                },
                "items": [
                    {
                        "codigo_interno": "ND-REC-1",
                        "descripcion": "Recupero de costo logístico",
                        "unidad_medida": "77",
                        "cantidad": "1",
                        "precio_unitario": "45000",
                        "afectacion": "gravado",
                        "tasa": 10,
                    }
                ],
            },
        ),
    ]
    return deepcopy(scenarios)
