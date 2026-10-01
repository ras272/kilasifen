"""Envio de eventos (cancelacion, inutilizacion, conformidad...) al SIFEN.

Ademas de :meth:`TransmisionEvento.enviar_evento`, la plataforma arma su
propio ``rEnviEventoDe`` como texto (para conservar la firma byte a byte) y lo
envia con ``_send_raw_xml("evento", xml)``, usando :func:`_generate_id` de
este modulo para el ``dId``.
"""

from __future__ import annotations

from typing import Any

from kilasifen.engine.de.bindings.v150.ws_si_recep_evento_v150 import (
    REnviEventoDe,
    RRetEnviEventoDe,
)
from kilasifen.engine.transmision.base import TransmisionBase, _generate_id

__all__ = ["TransmisionEvento"]


class TransmisionEvento(TransmisionBase):
    """Envia eventos de DE al web service de eventos del SIFEN."""

    def enviar_evento(self, evento: Any) -> RRetEnviEventoDe:
        """Envia un grupo de eventos (``gGroupGesEve``) dentro de ``rEnviEventoDe``.

        El evento no se firma aqui: debe llegar firmado si corresponde. Al
        reserializarse con xsdata, una firma calculada sobre otra forma textual
        puede dejar de verificar; para envios firmados conviene el camino
        crudo descrito en el modulo.
        """
        solicitud = REnviEventoDe(
            dId=_generate_id(),
            dEvReg=REnviEventoDe.DEvReg(gGroupGesEve=evento),
        )
        respuesta = self._get_client("evento").send(solicitud)
        return self._como_respuesta(respuesta, RRetEnviEventoDe)
