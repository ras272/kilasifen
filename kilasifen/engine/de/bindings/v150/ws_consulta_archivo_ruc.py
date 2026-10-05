from __future__ import annotations

from dataclasses import dataclass, field

from xsdata.models.datatype import XmlDate

from kilasifen.engine.binding import BindingMixin
from kilasifen.engine.de.bindings.v150.si_consulta_archivo_ruc import RConsultaArchivo

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


@dataclass(kw_only=True)
class REnviConsArchivoRucresponse(BindingMixin):
    """
    Attributes:
        dFecProc:
        dFecArchivo:
        dCodRes: Codigo de Respuesta
        dMsgRes: Mensaje del resultado de la consulta
        rConsDte: Archivo zip generado en la consulta de mis DTEs
    """

    class Meta:
        name = "rEnviConsArchivoRUCResponse"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    dFecProc: str = field(
        metadata={
            "type": "Element",
            "pattern": r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+|-]\d\d:\d\d",
        }
    )
    dFecArchivo: None | XmlDate = field(
        default=None,
        metadata={
            "type": "Element",
        },
    )
    dCodRes: str = field(
        metadata={
            "type": "Element",
            "min_length": 1,
            "max_length": 4,
        }
    )
    dMsgRes: str = field(
        metadata={
            "type": "Element",
            "min_length": 1,
            "max_length": 255,
        }
    )
    rConsDte: None | bytes = field(
        default=None,
        metadata={
            "type": "Element",
            "format": "base64",
        },
    )


@dataclass(kw_only=True)
class REnviConsArchivoRucrequest(BindingMixin):
    class Meta:
        name = "rEnviConsArchivoRUCRequest"
        namespace = "http://ekuatia.set.gov.py/sifen/xsd"

    rConsultaArchivo: RConsultaArchivo = field(
        metadata={
            "type": "Element",
        }
    )
