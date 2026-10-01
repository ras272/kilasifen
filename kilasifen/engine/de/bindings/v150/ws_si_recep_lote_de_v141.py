from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from kilasifen.engine.binding import BindingMixin

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


@dataclass(kw_only=True)
class REnvioLote(BindingMixin):
    """
    Recepcion de Documentos Electronicos por Lote.

    Attributes:
        dId: Identificador de control de envio
        xDE: XML del Documento Electronico Transferido
    """

    class Meta:
        name = "rEnvioLote"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    dId: int = field(
        metadata={
            "type": "Element",
            "min_inclusive": 1,
            "max_inclusive": 999999999999999,
        }
    )
    xDE: bytes = field(
        metadata={
            "type": "Element",
            "format": "base64",
        }
    )


@dataclass(kw_only=True)
class RResEnviLoteDe(BindingMixin):
    """
    Respuesta de la recepcion de Documentos Electronicos por Lote.

    Attributes:
        dFecProc:
        dCodRes: Código del resultado de recepción
        dMsgRes: Mensaje del resultado de recepción
        dProtConsLote: Número de Lote
        dTpoProces: Tiempo medio de procesamiento en segundos
    """

    class Meta:
        name = "rResEnviLoteDe"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    dFecProc: None | str = field(
        default=None,
        metadata={
            "type": "Element",
            "pattern": r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+|-]\d\d:\d\d",
        },
    )
    dCodRes: None | str = field(
        default=None,
        metadata={
            "type": "Element",
            "min_length": 1,
        },
    )
    dMsgRes: None | str = field(
        default=None,
        metadata={
            "type": "Element",
        },
    )
    dProtConsLote: None | Decimal = field(
        default=None,
        metadata={
            "type": "Element",
            "min_inclusive": Decimal("0"),
            "max_inclusive": Decimal("9999999999999999999999999999"),
            "total_digits": 28,
            "fraction_digits": 0,
        },
    )
    dTpoProces: None | int = field(
        default=None,
        metadata={
            "type": "Element",
        },
    )
