"""Validacion XML determinista con un registro explicito de XSD por raiz."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from lxml import etree

SCHEMA_REGISTRY: dict[str, dict[str, str]] = {
    "v150": {
        "rDE": "siRecepDE_v150.xsd",
        "rEnviDe": "WS_SiRecepDE_v150.xsd",
        "rRetEnviDe": "WS_SiRecepDE_v150.xsd",
        "rEnviEventoDe": "WS_SiRecepEvento_v150.xsd",
        "rRetEnviEventoDe": "WS_SiRecepEvento_v150.xsd",
        "rEnviConsDeRequest": "WS_SiConsDE_v141.xsd",
        "rEnviConsDeResponse": "WS_SiConsDE_v141.xsd",
        "rConsDteRequest": "WS_SiConsDTE.xsd",
        "rConsDteResponse": "WS_SiConsDTE.xsd",
        "rEnviConsDteAsyncRequest": "WS_SiConsDTEAsync.xsd",
        "rEnviConsDteAsyncResponse": "WS_SiConsDTEAsync.xsd",
        "rEnviConsLoteDe": "WS_SiConsLote_v141.xsd",
        "rResEnviConsLoteDe": "WS_SiConsLote_v141.xsd",
        "rEnviConsRUC": "WS_SiConsRUC_v141.xsd",
        "rResEnviConsRUC": "WS_SiConsRUC_v141.xsd",
        "rEnviConsArchivoRUCRequest": "WS_ConsultaArchivoRuc.xsd",
        "rEnviConsArchivoRUCResponse": "WS_ConsultaArchivoRuc.xsd",
        "rConsultaArchivo": "siConsultaArchivoRuc.xsd",
        "rConsultaDTE": "siConsultaDTE.xsd",
    }
}


def get_schema_dir(
    schema_family: str = "de",
    schema_version: str = "v150",
) -> Path:
    """Carpeta local de los XSD de una familia y version."""
    return (
        Path(__file__).resolve().parents[1]
        / schema_family
        / "schemas"
        / schema_version
    )


def resolve_schema_path(
    root_local_name: str,
    schema_family: str = "de",
    schema_version: str = "v150",
) -> Path | None:
    """XSD de entrada que corresponde al nombre local de la raiz."""
    registry = SCHEMA_REGISTRY.get(schema_version, {})
    schema_name = registry.get(root_local_name)
    if schema_name is None:
        return None
    return get_schema_dir(schema_family, schema_version) / schema_name


@lru_cache(maxsize=None)
def _load_schema(schema_path: str) -> etree.XMLSchema:
    """Compila un XSD una vez por ruta absoluta y lo reutiliza."""
    schema_doc = etree.parse(schema_path)
    return etree.XMLSchema(schema_doc)


def precargar_esquemas(
    *raices: str,
    schema_family: str = "de",
    schema_version: str = "v150",
) -> None:
    """Compila y deja en cache los XSD de esas raices.

    Sirve para compilarlos una sola vez en un proceso que despues se bifurca,
    como el worker de RQ: cada hijo hereda los esquemas ya compilados.

    Raises:
        ValueError: si una raiz no tiene un XSD registrado.
    """
    for raiz in raices:
        ruta = resolve_schema_path(
            raiz, schema_family=schema_family, schema_version=schema_version
        )
        if ruta is None:
            raise ValueError(
                f"No hay XSD registrado para la raiz {raiz!r} en {schema_version!r}"
            )
        _load_schema(str(ruta.resolve()))


def validate_xml(
    xml_string: str,
    schema_family: str = "de",
    schema_version: str = "v150",
) -> list[str]:
    """Valida un XML contra el XSD que le corresponde por su raiz."""
    try:
        xml_doc = etree.fromstring(xml_string.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        return [str(exc)]

    root_local_name = etree.QName(xml_doc).localname
    schema_path = resolve_schema_path(
        root_local_name,
        schema_family=schema_family,
        schema_version=schema_version,
    )
    if schema_path is None:
        return [
            (
                "No schema registered for root element "
                f"'{root_local_name}' in version '{schema_version}'."
            )
        ]

    try:
        schema = _load_schema(str(schema_path.resolve()))
        schema.assertValid(xml_doc)
    except etree.DocumentInvalid as exc:
        return [str(error) for error in exc.error_log]
    except (OSError, etree.XMLSchemaParseError) as exc:
        return [str(exc)]

    return []
