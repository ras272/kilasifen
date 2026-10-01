from __future__ import annotations

from dataclasses import dataclass, field

from kilasifen.engine.binding import BindingMixin
from kilasifen.engine.de.bindings.v150.xmldsig_core_schema import Signature

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


@dataclass(kw_only=True)
class RConsultaArchivo(BindingMixin):
    """
    Attributes:
        ConsultaDTE:
        Signature: Firma Digital de la ConsultaDTE
    """

    class Meta:
        name = "rConsultaArchivo"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    ConsultaDTE: RConsultaArchivo.ConsultaDte = field(
        metadata={
            "type": "Element",
        }
    )
    Signature: Signature = field(
        metadata={
            "type": "Element",
            "namespace": "http://www.w3.org/2000/09/xmldsig#",
        }
    )

    @dataclass(kw_only=True)
    class ConsultaDte(BindingMixin):
        dRucFactElec: str = field(
            metadata={
                "type": "Element",
                "min_length": 5,
                "max_length": 8,
                "pattern": r"[1-9][0-9]*[0-9A-D]?",
            }
        )
        Id: str = field(
            metadata={
                "type": "Attribute",
            }
        )
