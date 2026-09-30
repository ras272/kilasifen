"""Comportamiento compartido por todas las clases generadas desde los XSD del SIFEN.

El generador (``scripts/generate_bindings.py``) configura xsdata para que cada
dataclass generada herede de :class:`BindingMixin`. Asi cualquier nodo del
arbol (``RDe``, ``REnviDe``, ``REnviEventoDe``...) sabe leerse desde XML,
serializarse, validarse contra su XSD y firmarse sin codigo adicional.

El parser y los serializadores de xsdata se construyen una sola vez y se
reutilizan: crearlos es costoso (contexto de metadatos, configuracion) y la
plataforma serializa miles de documentos por proceso.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

__all__ = ["BindingMixin"]

_T = TypeVar("_T", bound="BindingMixin")

#: Familia/version usadas cuando la clase no vive en un paquete de bindings.
_FAMILIA_POR_DEFECTO = "de"
_VERSION_POR_DEFECTO = "v150"

#: Sangria del modo "pretty": dos espacios por nivel.
_SANGRIA = "  "


@lru_cache(maxsize=1)
def _parser_compartido() -> XmlParser:
    """Devuelve el unico ``XmlParser`` del proceso."""
    return XmlParser()


@lru_cache(maxsize=2)
def _serializador_compartido(con_sangria: bool) -> XmlSerializer:
    """Devuelve un ``XmlSerializer`` por modo de salida (con o sin sangria)."""
    config = SerializerConfig(
        encoding="UTF-8",
        xml_declaration=True,
        indent=_SANGRIA if con_sangria else None,
    )
    return XmlSerializer(config=config)


def _familia_y_version(modulo: str) -> tuple[str, str]:
    """Deduce ``(familia, version)`` de una ruta de modulo de bindings.

    Las clases generadas viven en ``kilasifen.engine.<familia>.bindings.<version>``;
    por ejemplo ``kilasifen.engine.de.bindings.v150.fe_v141`` -> ``("de", "v150")``.
    Para cualquier otro modulo se usan los valores por defecto.
    """
    partes = modulo.split(".")
    try:
        pos = partes.index("bindings")
    except ValueError:
        return _FAMILIA_POR_DEFECTO, _VERSION_POR_DEFECTO
    if pos == 0 or pos + 1 >= len(partes):
        return _FAMILIA_POR_DEFECTO, _VERSION_POR_DEFECTO
    return partes[pos - 1], partes[pos + 1]


class BindingMixin:
    """Metodos de conveniencia inyectados en cada dataclass generada."""

    @classmethod
    def from_xml(cls: type[_T], xml: str) -> _T:
        """Construye la instancia a partir de un texto XML."""
        return _parser_compartido().from_string(xml, cls)

    @classmethod
    def from_path(cls: type[_T], path: str | os.PathLike[str]) -> _T:
        """Construye la instancia leyendo un archivo XML del disco."""
        return _parser_compartido().from_path(Path(os.fspath(path)), cls)

    def to_xml(self, pretty_print: bool = True) -> str:
        """Serializa la instancia como XML UTF-8 con declaracion inicial.

        Con ``pretty_print=True`` cada nivel se indenta con dos espacios; con
        ``False`` el documento sale en una sola linea (forma usada para firmar
        y transmitir).
        """
        return _serializador_compartido(bool(pretty_print)).render(self)

    def validate_xml(self) -> list[str]:
        """Valida el XML serializado contra el XSD que le corresponde.

        Devuelve la lista de errores del esquema; vacia si el documento es valido.
        """
        from kilasifen.engine.sdk.validation import validate_xml

        familia, version = _familia_y_version(type(self).__module__)
        return validate_xml(
            self.to_xml(),
            schema_family=familia,
            schema_version=version,
        )

    def sign_xml(
        self,
        xml: str | bytes | None,
        pkcs12_data: bytes,
        pkcs12_password: str | bytes,
        doc_id: str,
    ) -> str:
        """Firma ``xml`` (o, si es ``None``, esta misma instancia) con XMLDSig.

        Delega en :func:`kilasifen.engine.firma.sign_xml`. Requiere el extra
        de firma: ``pip install "kilasifen[sign]"``; si falta, se lanza
        ``ImportError`` con esa indicacion.
        """
        from kilasifen.engine.firma import sign_xml

        if xml is None:
            xml = self.to_xml(pretty_print=False)
        return sign_xml(xml, pkcs12_data, pkcs12_password, doc_id)
