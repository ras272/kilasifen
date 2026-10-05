"""Catalogos oficiales derivados de los XSD (departamentos, paises y monedas)."""

from pathlib import Path
from xml.etree import ElementTree as ET

from kilasifen.engine.sdk.catalogos import (
    DEPARTAMENTOS,
    descripcion_departamento,
    descripcion_moneda,
    descripcion_pais,
    monedas,
    paises,
)

_XS = "{http://www.w3.org/2001/XMLSchema}"
_SCHEMAS = Path(__file__).resolve().parents[1] / "kilasifen/engine/de/schemas/v150"


def _documentacion(archivo: str, tipo: str) -> dict[str, str]:
    raiz = ET.parse(_SCHEMAS / archivo).getroot()
    simple = next(
        nodo for nodo in raiz.iter(f"{_XS}simpleType") if nodo.get("name") == tipo
    )
    return {
        enumeracion.get("value"): enumeracion.find(
            f"{_XS}annotation/{_XS}documentation"
        ).text.strip()
        for enumeracion in simple.iter(f"{_XS}enumeration")
    }


def test_departamentos_coinciden_con_las_anotaciones_del_xsd() -> None:
    esperado = {
        int(codigo): descripcion
        for codigo, descripcion in _documentacion(
            "Departamentos_v141.xsd", "tDepartamentos"
        ).items()
    }

    assert dict(DEPARTAMENTOS) == esperado
    assert len(DEPARTAMENTOS) == 20


def test_descripcion_de_departamento_conocido_y_desconocido() -> None:
    assert descripcion_departamento(1) == "CAPITAL"
    assert descripcion_departamento(12) == "CENTRAL"
    assert descripcion_departamento(21) is None


def test_paises_traen_la_descripcion_oficial_del_xsd() -> None:
    assert descripcion_pais("PRY") == "Paraguay"
    assert descripcion_pais("ARG") == "Argentina"
    assert descripcion_pais("XXX") is None
    # tDesPais (NT 05): todas las descripciones caben en 4-50 caracteres.
    assert all(4 <= len(descripcion) <= 50 for descripcion in paises().values())


def test_monedas_traen_el_codename_oficial_del_xsd() -> None:
    raiz = ET.parse(_SCHEMAS / "Monedas_v150.xsd").getroot()
    simple = next(
        nodo for nodo in raiz.iter(f"{_XS}simpleType") if nodo.get("name") == "cMondT"
    )
    codigos = [nodo.get("value") for nodo in simple.iter(f"{_XS}enumeration")]

    assert list(monedas()) == codigos
    assert all(monedas().values())
    # D016/E610/E654 son "Referente al campo" D015/E609/E653 (1206, 1555).
    assert descripcion_moneda("PYG") == "Guarani"
    assert descripcion_moneda("USD") == "US Dollar"
    assert descripcion_moneda("BRL") == "Brazilian Real"
    assert descripcion_moneda("XYZ") is None
