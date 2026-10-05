"""Bindings generados para los Web Services del SIFEN.

Comprueba que las clases de peticion y respuesta de cada servicio existen,
son dataclasses y heredan los metodos de ``BindingMixin``. No lee muestras.
"""

from __future__ import annotations

import dataclasses
import importlib

from kilasifen.engine.binding import BindingMixin

_PAQUETE = "kilasifen.engine.de.bindings.v150"


def _clase(modulo: str, nombre: str) -> type:
    """Importa ``nombre`` desde el modulo de bindings ``modulo``."""
    return getattr(importlib.import_module(f"{_PAQUETE}.{modulo}"), nombre)


def _verificar_bindings(modulo: str, *nombres: str) -> None:
    """Cada clase existe, es dataclass y hereda de ``BindingMixin``."""
    for nombre in nombres:
        clase = _clase(modulo, nombre)
        assert dataclasses.is_dataclass(clase), f"{modulo}.{nombre}"
        assert issubclass(clase, BindingMixin), f"{modulo}.{nombre}"


class TestBindingsRecepcion:
    """Servicios de recepcion de documentos, eventos y lotes."""

    def test_recepcion_de_peticion_y_respuesta(self) -> None:
        _verificar_bindings("ws_si_recep_de_v150", "REnviDe", "RRetEnviDe")

    def test_recepcion_evento_peticion_y_respuesta(self) -> None:
        _verificar_bindings(
            "ws_si_recep_evento_v150", "REnviEventoDe", "RRetEnviEventoDe"
        )

    def test_recepcion_lote_peticion_y_respuesta(self) -> None:
        _verificar_bindings(
            "ws_si_recep_lote_de_v141", "REnvioLote", "RResEnviLoteDe"
        )


class TestBindingsConsulta:
    """Servicios de consulta de documentos, lotes, RUC y DTE."""

    def test_consulta_de_peticion_y_respuesta(self) -> None:
        _verificar_bindings(
            "ws_si_cons_de_v141", "REnviConsDeRequest", "REnviConsDeResponse"
        )

    def test_consulta_lote_peticion_y_respuesta(self) -> None:
        _verificar_bindings(
            "ws_si_cons_lote_v141", "REnviConsLoteDe", "RResEnviConsLoteDe"
        )

    def test_consulta_ruc_peticion_y_respuesta(self) -> None:
        _verificar_bindings("ws_si_cons_ruc_v141", "REnviConsRuc", "RResEnviConsRuc")

    def test_consulta_dte_peticion_y_respuesta(self) -> None:
        _verificar_bindings("ws_si_cons_dte", "RConsDteRequest", "RConsDteResponse")


class TestBindingsProtocolo:
    """Protocolos de procesamiento de documentos y eventos."""

    def test_protocolo_de_es_dataclass(self) -> None:
        _verificar_bindings("prot_proces_de_v150", "RProtDe")

    def test_protocolo_eventos_son_dataclasses(self) -> None:
        _verificar_bindings("prot_proces_eventos_v141", "TgResProc", "TgResProcEve")


class TestMixinEnBindingsWs:
    """Las clases de los Web Services exponen los metodos del mixin."""

    def test_clase_ws_expone_metodos_del_mixin(self) -> None:
        clase = _clase("ws_si_recep_de_v150", "REnviDe")
        for nombre in ("from_xml", "to_xml", "from_path"):
            assert callable(getattr(clase, nombre, None)), nombre
