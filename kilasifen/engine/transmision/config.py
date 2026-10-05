"""Ambientes del SIFEN y direcciones de sus web services.

Cada ambiente (produccion o pruebas) expone el mismo conjunto de servicios en
un servidor distinto. Los POST se dirigen exactamente a estas direcciones,
incluido el sufijo ``.wsdl``, que es como el SIFEN publica sus puntos de
acceso.
"""

from __future__ import annotations

__all__ = [
    "ENDPOINTS",
    "PRODUCCION",
    "SERVICIOS_EXPERIMENTALES",
    "TEST",
    "get_endpoint",
]

#: Ambiente de produccion (documentos con validez fiscal).
PRODUCCION: int = 1

#: Ambiente de pruebas de la SET.
TEST: int = 2

#: Servidor de cada ambiente.
_SERVIDORES: dict[int, str] = {
    PRODUCCION: "https://sifen.set.gov.py",
    TEST: "https://sifen-test.set.gov.py",
}

#: Ruta de cada servicio dentro del servidor. El orden de las claves es el
#: que se muestra al informar un servicio desconocido. Las seis primeras son
#: las del MT v150 sec. 7.10 (p. 41) y la Guia de mejores practicas
#: (oct-2024, p. 5).
_RUTAS_DE_SERVICIO: dict[str, str] = {
    "recep_de": "/de/ws/sync/recibe.wsdl",
    "recep_lote": "/de/ws/async/recibe-lote.wsdl",
    "cons_de": "/de/ws/consultas/consulta.wsdl",
    "cons_lote": "/de/ws/consultas/consulta-lote.wsdl",
    "cons_ruc": "/de/ws/consultas/consulta-ruc.wsdl",
    "evento": "/de/ws/eventos/evento.wsdl",
    # EXPERIMENTAL: rutas sin respaldo oficial (ver SERVICIOS_EXPERIMENTALES).
    "cons_dte": "/de/ws/consultas/consulta-dte.wsdl",
    "cons_dte_async": "/de/ws/consultas/consulta-dte-async.wsdl",
}

#: Servicios EXPERIMENTALES y no documentados: la consulta DTE sincronica y
#: asincronica. La SET publica sus XSD (``WS_SiConsDTE.xsd`` y
#: ``WS_SiConsDTEAsync.xsd``), pero su direccion, sus codigos de resultado,
#: sus plazos y si el servicio esta habilitado no figuran en el MT v150 (sec.
#: 7.10, p. 41), en las NT 01 a 27, en la Guia de mejores practicas (p. 5),
#: en la Guia de pruebas (feb-2026, p. 6) ni en la FAQ de la DNIT (NO
#: DETERMINADO). Sus rutas son una suposicion y pueden no existir.
SERVICIOS_EXPERIMENTALES: frozenset[str] = frozenset({"cons_dte", "cons_dte_async"})

#: Direccion completa de cada servicio, agrupada por ambiente.
ENDPOINTS: dict[int, dict[str, str]] = {
    ambiente: {
        servicio: servidor + ruta for servicio, ruta in _RUTAS_DE_SERVICIO.items()
    }
    for ambiente, servidor in _SERVIDORES.items()
}


def get_endpoint(ambiente: int, servicio: str) -> str:
    """Devuelve la direccion del ``servicio`` en el ``ambiente`` indicado.

    La tabla :data:`ENDPOINTS` se consulta en cada llamada, de modo que un
    cambio hecho sobre ella en tiempo de ejecucion se respeta.

    Raises:
        ValueError: si el ambiente o el servicio no existen. El ambiente se
            verifica primero.
    """
    if ambiente not in ENDPOINTS:
        raise ValueError(
            f"Ambiente SIFEN desconocido: {ambiente!r}. "
            "Valores admitidos: PRODUCCION=1, TEST=2"
        )
    servicios = ENDPOINTS[ambiente]
    if servicio not in servicios:
        raise ValueError(
            f"Servicio SIFEN desconocido: {servicio!r}. "
            f"Servicios admitidos: {', '.join(servicios)}"
        )
    return servicios[servicio]
