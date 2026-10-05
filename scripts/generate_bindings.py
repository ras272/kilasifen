#!/usr/bin/env python
"""Regenera los bindings Python del SIFEN a partir de los XSD oficiales.

Toma todos los ``*.xsd`` de ``kilasifen/engine/<familia>/schemas/<version>/``
y genera, con xsdata, los modulos de dataclasses del paquete
``kilasifen.engine.<familia>.bindings.<version>``. Cada modulo toma el nombre
del XSD que define sus tipos; los esquemas que solo repiten o envuelven tipos
ya definidos en otro archivo no producen modulo propio (hoy: 47 XSD, 26
modulos).

Uso (desde cualquier directorio)::

    python scripts/generate_bindings.py            # regenera v150
    python scripts/generate_bindings.py --check    # solo verifica que no haya deriva

Requisitos (solo para desarrollo, no son dependencias de ejecucion)::

    pip install "xsdata[cli]==26.2"

``xsdata[cli]`` trae ``ruff``, que xsdata usa para formatear lo generado; su
ejecutable tiene que estar en el ``PATH`` (este script agrega automaticamente
la carpeta de scripts del interprete actual, p. ej. ``.venv/Scripts``).

Los bindings versionados en el repositorio se generaron con **xsdata 26.2**
(Python 3.14). Otra version de xsdata puede producir codigo con otro formato;
si se actualiza, hay que volver a correr este script y los tests.

Decisiones de generacion:

* dataclasses, un modulo por XSD (estilo de estructura ``filenames``);
* clases en PascalCase, modulos en snake_case y campos con el nombre ORIGINAL
  del XSD (``dRucEm``, ``iTiDE``...), para que el codigo refleje las etiquetas
  del Manual Tecnico;
* imports absolutos;
* cada clase generada hereda de :class:`kilasifen.engine.binding.BindingMixin`
  (``from_xml``, ``to_xml``, ``validate_xml``, ``sign_xml``...).

Los XSD se procesan en orden alfabetico. Algunos esquemas del SIFEN redefinen
tipos con el mismo nombre (p. ej. versiones 141 y 150 conviviendo); xsdata se
queda con la ultima definicion, por lo que el orden importa y es fijo.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
import sysconfig
import tempfile
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
VERSION_XSDATA_ESPERADA = "26.2"
MIXIN = "kilasifen.engine.binding.BindingMixin"


def _paquete(familia: str, version: str) -> str:
    return f"kilasifen.engine.{familia}.bindings.{version}"


def _dir_esquemas(familia: str, version: str) -> Path:
    return RAIZ_REPO / "kilasifen" / "engine" / familia / "schemas" / version


def _dir_paquete(base: Path, paquete: str) -> Path:
    return base.joinpath(*paquete.split("."))


def _configuracion(paquete: str):
    """Arma la configuracion de xsdata equivalente a un ``.xsdata.xml``."""
    from xsdata.models.config import (
        DocstringStyle,
        ExtensionType,
        GeneratorConfig,
        GeneratorExtension,
        NameCase,
        NameConvention,
        StructureStyle,
    )

    config = GeneratorConfig()
    salida = config.output
    salida.package = paquete
    salida.structure_style = StructureStyle.FILENAMES
    salida.docstring_style = DocstringStyle.GOOGLE
    salida.relative_imports = False
    salida.max_line_length = 100
    salida.format.value = "dataclasses"

    convenciones = config.conventions
    convenciones.class_name = NameConvention(NameCase.PASCAL, "type")
    convenciones.field_name = NameConvention(NameCase.ORIGINAL, "value")
    convenciones.module_name = NameConvention(NameCase.SNAKE, "mod")
    convenciones.package_name = NameConvention(NameCase.SNAKE, "pkg")

    config.extensions.extension.append(
        GeneratorExtension(
            type=ExtensionType.CLASS,
            class_name=".*",
            import_string=MIXIN,
        )
    )
    return config


def _asegurar_ruff_en_path() -> None:
    """xsdata invoca ``ruff`` como proceso externo; lo buscamos junto al interprete."""
    scripts = sysconfig.get_path("scripts")
    if scripts and scripts not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = scripts + os.pathsep + os.environ.get("PATH", "")
    if shutil.which("ruff") is None:
        sys.exit('No se encontro "ruff". Instala: pip install "xsdata[cli]==26.2"')


def _generar(esquemas: list[Path], paquete: str, destino_base: Path) -> Path:
    """Genera ``paquete`` debajo de ``destino_base`` y devuelve su carpeta."""
    from xsdata.codegen.transformer import ResourceTransformer

    carpeta = _dir_paquete(destino_base, paquete)
    if carpeta.exists():
        for viejo in carpeta.glob("*.py"):
            viejo.unlink()
        shutil.rmtree(carpeta / "__pycache__", ignore_errors=True)

    anterior = Path.cwd()
    os.chdir(destino_base)  # xsdata escribe el paquete relativo al cwd
    try:
        uris = [esquema.resolve().as_uri() for esquema in esquemas]
        ResourceTransformer(_configuracion(paquete)).process(uris)
    finally:
        os.chdir(anterior)
    return carpeta


def _diferencias(esperado: Path, actual: Path) -> list[str]:
    nombres = sorted(
        {p.name for p in esperado.glob("*.py")} | {p.name for p in actual.glob("*.py")}
    )
    distintos = []
    for nombre in nombres:
        a, b = esperado / nombre, actual / nombre
        if not (a.exists() and b.exists() and filecmp.cmp(a, b, shallow=False)):
            distintos.append(nombre)
    return distintos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--family", default="de", help="familia de esquemas (default: de)"
    )
    parser.add_argument(
        "--version", default="v150", help="version de esquemas (default: v150)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="genera en un directorio temporal y falla si difiere de lo versionado",
    )
    args = parser.parse_args(argv)

    import xsdata

    if xsdata.__version__ != VERSION_XSDATA_ESPERADA:
        print(
            f"Aviso: xsdata {xsdata.__version__} instalado; los bindings versionados "
            f"se generaron con {VERSION_XSDATA_ESPERADA}.",
            file=sys.stderr,
        )

    _asegurar_ruff_en_path()
    esquemas = sorted(
        _dir_esquemas(args.family, args.version).glob("*.xsd"), key=lambda p: p.name
    )
    if not esquemas:
        sys.exit(f"No hay XSD en {_dir_esquemas(args.family, args.version)}")
    paquete = _paquete(args.family, args.version)

    if not args.check:
        carpeta = _generar(esquemas, paquete, RAIZ_REPO)
        print(f"{len(list(carpeta.glob('*.py')))} modulos escritos en {carpeta}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        generado = _generar(esquemas, paquete, Path(tmp))
        distintos = _diferencias(_dir_paquete(RAIZ_REPO, paquete), generado)
    if distintos:
        print("Bindings desactualizados: " + ", ".join(distintos), file=sys.stderr)
        return 1
    print("Bindings al dia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
