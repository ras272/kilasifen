"""Read-side SIFEN query adapters built on top of kilasifen.engine."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.emitters.models import Emitter
from kilasifen.engine import PRODUCCION, TEST, ConsultaSIFEN
from kilasifen.engine.de.bindings.v150.ws_si_cons_de_v141 import (
    REnviConsDeRequest,
    REnviConsDeResponse,
)
from kilasifen.engine.de.bindings.v150.ws_si_cons_ruc_v141 import (
    REnviConsRuc,
    RResEnviConsRuc,
)
from kilasifen.engine.sdk.errors import SifenValidationError


@dataclass(slots=True)
class RucQueryOutcome:
    """Normalized result from a SIFEN RUC query."""

    queried_ruc: str
    request_xml: str
    response_raw: str
    result_code: str | None
    result_message: str | None
    status: str
    taxpayer_ruc: str | None
    taxpayer_legal_name: str | None
    taxpayer_state_code: str | None
    taxpayer_state: str | None
    electronic_taxpayer: bool | None


@dataclass(slots=True)
class DocumentQueryOutcome:
    """Normalized result from a SIFEN document query."""

    cdc: str
    request_xml: str
    response_raw: str
    result_code: str | None
    result_message: str | None
    status: str
    content_xml: str | None
    processed_at: datetime | None


class SifenQueryGateway(Protocol):
    """Contract for read-side SIFEN queries."""

    def query_ruc(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        ruc: str,
    ) -> RucQueryOutcome:
        """Query one taxpayer RUC."""

    def query_document(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        cdc: str,
    ) -> DocumentQueryOutcome:
        """Query one document by CDC."""


class PysifenQueryGateway:
    """Concrete query gateway backed by kilasifen.engine transport."""

    def __init__(self, deployment_environment: str = "test"):
        self.deployment_environment = deployment_environment
        self.serializer = XmlSerializer(
            config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
        )

    def query_ruc(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        ruc: str,
    ) -> RucQueryOutcome:
        normalized_ruc = _normalize_ruc(ruc)
        request = REnviConsRuc(dId=_generate_query_id(), dRUCCons=normalized_ruc)
        response = self._run_consulta(
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            operation=lambda consulta: consulta.consultar_ruc(ruc),
        )
        assert isinstance(response, RResEnviConsRuc)
        taxpayer = response.xContRUC
        return RucQueryOutcome(
            queried_ruc=normalized_ruc,
            request_xml=self.serializer.render(request),
            response_raw=self.serializer.render(response),
            result_code=response.dCodRes,
            result_message=response.dMsgRes,
            status="found" if taxpayer is not None else "not_found",
            taxpayer_ruc=getattr(taxpayer, "dRUCCons", None),
            taxpayer_legal_name=getattr(taxpayer, "dRazCons", None),
            taxpayer_state_code=getattr(taxpayer, "dCodEstCons", None),
            taxpayer_state=getattr(taxpayer, "dDesEstCons", None),
            electronic_taxpayer=_normalize_electronic_flag(
                getattr(taxpayer, "dRUCFactElec", None)
            ),
        )

    def query_document(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        cdc: str,
    ) -> DocumentQueryOutcome:
        request = REnviConsDeRequest(dId=_generate_query_id(), dCDC=cdc)
        response = self._run_consulta(
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            operation=lambda consulta: consulta.consultar_de(cdc),
        )
        assert isinstance(response, REnviConsDeResponse)
        processed_at = None
        if response.dFecProc:
            processed_at = datetime.fromisoformat(response.dFecProc)
        return DocumentQueryOutcome(
            cdc=cdc,
            request_xml=self.serializer.render(request),
            response_raw=self.serializer.render(response),
            result_code=response.dCodRes,
            result_message=response.dMsgRes,
            status="found" if response.xContenDE else "not_found",
            content_xml=response.xContenDE,
            processed_at=processed_at,
        )

    def _run_consulta(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        operation,
    ):
        if emitter.tax_environment != self.deployment_environment:
            raise SifenValidationError(
                "Emitter tax environment does not match this deployment"
            )
        ambiente = TEST if emitter.tax_environment == "test" else PRODUCCION
        with ConsultaSIFEN(
            ambiente=ambiente,
            pkcs12_data=certificate_bytes,
            pkcs12_password=certificate_password,
        ) as consulta:
            return operation(consulta)


def _normalize_ruc(ruc: str) -> str:
    value = str(ruc).strip().replace(" ", "")
    if "-" in value:
        parts = value.split("-")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Formato de RUC invalido: '{ruc}'")
        value = parts[0]
    return value


def _generate_query_id() -> int:
    return int(time.time() * 1000) % 999999999999999


def _normalize_electronic_flag(raw_value: str | None) -> bool | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip().upper()
    if normalized in {"S", "SI", "1"}:
        return True
    if normalized in {"N", "NO", "0"}:
        return False
    return None
