"""Bindings generados para los eventos del SIFEN (``Evento_v150.xsd``).

Comprueba que la raiz del evento y los grupos de cada tipo de evento existen,
son dataclasses con los campos que define el XSD y exponen los metodos de
``BindingMixin``. No lee muestras.
"""

from __future__ import annotations

import dataclasses

from kilasifen.engine.de.bindings.v150 import evento_types_v150, evento_v150


def _campos(clase: type) -> set[str]:
    """Nombres de los campos de una dataclass generada."""
    return {campo.name for campo in dataclasses.fields(clase)}


class TestBindingsDeEventos:
    """Raiz, tipos y grupos de los eventos."""

    def test_evento_raiz_es_dataclass(self) -> None:
        assert dataclasses.is_dataclass(evento_v150.TrEve)
        assert {"Id", "dFecFirma", "dVerFor", "gGroupTiEvt"} <= _campos(
            evento_v150.TrEve
        )

    def test_tipos_de_evento_importables(self) -> None:
        tipos = evento_types_v150.TiTipEve
        assert tipos is not None
        assert {1, 2} <= {miembro.value for miembro in tipos}

    def test_evento_cancelacion_tiene_campos(self) -> None:
        campos = _campos(evento_v150.TrGeVeCan)
        assert len(campos) >= 1
        assert {"Id", "mOtEve"} <= campos

    def test_evento_inutilizacion_tiene_campos(self) -> None:
        campos = _campos(evento_v150.TrGeVeInu)
        assert len(campos) >= 1
        assert {
            "dNumTim",
            "dEst",
            "dPunExp",
            "dNumIn",
            "dNumFin",
            "iTiDE",
            "mOtEve",
        } <= campos

    def test_evento_conformidad_tiene_campos(self) -> None:
        campos = _campos(evento_v150.TrGeVeConf)
        assert len(campos) >= 1
        assert {"Id", "iTipConf"} <= campos

    def test_evento_disconformidad_tiene_campos(self) -> None:
        campos = _campos(evento_v150.TrGeVeDisconf)
        assert len(campos) >= 1
        assert {"Id", "mOtEve"} <= campos

    def test_evento_nominacion_tiene_campos(self) -> None:
        # El generador produce ``TrGeveNom`` (con "v" minuscula) desde el XSD.
        campos = _campos(evento_v150.TrGeveNom)
        assert len(campos) >= 1
        assert {"Id", "mOtEve", "dNomRec"} <= campos

    def test_evento_expone_metodos_del_mixin(self) -> None:
        for nombre in ("from_xml", "to_xml"):
            assert callable(getattr(evento_v150.TrEve, nombre, None)), nombre
