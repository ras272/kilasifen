from __future__ import annotations

from dataclasses import dataclass, field

from kilasifen.engine.binding import BindingMixin
from kilasifen.engine.de.bindings.v150.evento_v150 import TgGroupGesEve
from kilasifen.engine.de.bindings.v150.prot_proces_eventos_v141 import TgResProcEve

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


@dataclass(kw_only=True)
class REnviEventoDe(BindingMixin):
    """
    Recepcion de Eventos de Documentos Electronicos.

    Attributes:
        dId: Identificador de control de envio
        dEvReg: Evento a ser registrado
    """

    class Meta:
        name = "rEnviEventoDe"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    dId: int = field(
        metadata={
            "type": "Element",
            "total_digits": 15,
        }
    )
    dEvReg: REnviEventoDe.DEvReg = field(
        metadata={
            "type": "Element",
        }
    )

    @dataclass(kw_only=True)
    class DEvReg(BindingMixin):
        gGroupGesEve: TgGroupGesEve = field(
            metadata={
                "type": "Element",
            }
        )


@dataclass(kw_only=True)
class RRetEnviEventoDe(BindingMixin):
    """
    Respuesta de Eventos.

    Attributes:
        dFecProc:
        gResProcEVe: Grupo Resultado de Procesamiento del Evento
    """

    class Meta:
        name = "rRetEnviEventoDe"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    dFecProc: str = field(
        metadata={
            "type": "Element",
            "pattern": r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+|-]\d\d:\d\d",
        }
    )
    gResProcEVe: list[TgResProcEve] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "min_occurs": 1,
            "max_occurs": 15,
        },
    )
