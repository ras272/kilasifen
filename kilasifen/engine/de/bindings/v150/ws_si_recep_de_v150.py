from __future__ import annotations

from dataclasses import dataclass, field

from kilasifen.engine.binding import BindingMixin
from kilasifen.engine.de.bindings.v150.prot_proces_de_v150 import RProtDe

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


@dataclass(kw_only=True)
class REnviDe(BindingMixin):
    """
    Recepcion de Documentos Electronicos.

    Attributes:
        dId: Identificador de control de envio
        xDE: XML del Documento Electronico Transferido
    """

    class Meta:
        name = "rEnviDe"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    dId: int = field(
        metadata={
            "type": "Element",
            "total_digits": 15,
        }
    )
    xDE: REnviDe.XDe = field(
        metadata={
            "type": "Element",
        }
    )

    @dataclass(kw_only=True)
    class XDe(BindingMixin):
        ekuatia_set_gov_pysifenxsd_element: None | object = field(
            default=None,
            metadata={
                "type": "Wildcard",
                "process_contents": "skip",
            },
        )


@dataclass(kw_only=True)
class RRetEnviDe(BindingMixin):
    """
    Respuesta de la recepcion de Documentos Electronicos.

    Attributes:
        rProtDe: Protocolo de procesamiento de DE
    """

    class Meta:
        name = "rRetEnviDe"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    rProtDe: RProtDe = field(
        metadata={
            "type": "Element",
        }
    )
