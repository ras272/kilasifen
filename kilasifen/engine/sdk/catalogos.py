"""Catalogos oficiales del SIFEN derivados de los XSD de la SET.

- Departamentos (``tDepartamentos`` / ``tDesDepartamento``): salen de los
  bindings generados desde ``Departamentos_v141.xsd``. Las dos enumeraciones
  se declaran en el mismo orden del XSD, codigo 1 a 20, y se emparejan por
  posicion; ``tests/test_catalogos.py`` lo contrasta con las anotaciones del
  XSD para detectar cualquier deriva.
- Paises (``paisType``): el binding solo trae los codigos ISO 3166, asi que la
  descripcion se lee de la anotacion de cada enumeracion de
  ``Paises_v100.xsd`` (MT v150 D203/D204 y validacion 1301).
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree as ET

from kilasifen.engine.de.bindings.v150.departamentos_v141 import (
    TDepartamentos,
    TDesDepartamento,
)

_XS = "{http://www.w3.org/2001/XMLSchema}"
_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "de" / "schemas" / "v150"

#: Codigo de departamento (D111/D219) -> descripcion oficial (D112/D220).
DEPARTAMENTOS: Mapping[int, str] = MappingProxyType(
    {
        codigo.value: descripcion.value
        for codigo, descripcion in zip(TDepartamentos, TDesDepartamento, strict=True)
    }
)


def descripcion_departamento(codigo: int) -> str | None:
    """Devuelve la descripcion oficial del departamento, o ``None``."""

    return DEPARTAMENTOS.get(codigo)


@lru_cache(maxsize=1)
def paises() -> Mapping[str, str]:
    """Codigo ISO 3166 alfa-3 (D203) -> descripcion oficial (D204)."""

    return MappingProxyType(_enumeracion_documentada("Paises_v100.xsd", "paisType"))


def descripcion_pais(codigo: str) -> str | None:
    """Devuelve la descripcion oficial del pais, o ``None``."""

    return paises().get(codigo)


def _enumeracion_documentada(archivo: str, tipo: str) -> dict[str, str]:
    raiz = ET.parse(_SCHEMAS_DIR / archivo).getroot()
    for simple in raiz.iter(f"{_XS}simpleType"):
        if simple.get("name") != tipo:
            continue
        valores: dict[str, str] = {}
        for enumeracion in simple.iter(f"{_XS}enumeration"):
            documentacion = enumeracion.find(f"{_XS}annotation/{_XS}documentation")
            texto = documentacion.text if documentacion is not None else None
            valores[enumeracion.get("value", "")] = (texto or "").strip()
        return valores
    raise LookupError(f"{archivo} no declara el tipo {tipo}")
