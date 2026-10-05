"""Read-side SIFEN query adapters built on top of kilasifen.engine.

A query by CDC (siConsDE) is read by its code (DECISIONES F62): 0422 means
the CDC is an approved DTE and ``xContenDE`` carries the container
``rContDe{rDE, dProtAut, xContEv}`` (MT v150 Tabla G p. 51, Schemas XML 11-12
pp. 51-52); 0420 means "no existe o no esta aprobado" (Guia de Mejores
Practicas DNIT oct-2024 p. 12); any other code (0421, 01xx, 0380) is an
error, never a "not found". The request stored for audit is the exact text
that travelled, with its real ``dId``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.common.sifen_results import (
    QUERY_FOUND_CODE,
    QUERY_NOT_FOUND_OR_NOT_APPROVED_CODE,
)
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
from kilasifen.engine.transmision.consulta import _es_cdc_valido
from kilasifen.infrastructure.sifen.de_facts import parse_sifen_datetime
from kilasifen.infrastructure.sifen.responses import (
    DocumentContainer,
    read_document_container,
)

#: ``DocumentQueryOutcome.status`` values.
QUERY_FOUND = "found"
QUERY_NOT_FOUND_OR_NOT_APPROVED = "not_found_or_not_approved"
QUERY_ERROR = "error"


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
    """Normalized result from a SIFEN document query.

    ``status`` is ``found`` (0422), ``not_found_or_not_approved`` (0420) or
    ``error``. ``content_xml`` is ``xContenDE`` as received and
    ``container`` its reading: the DTE, ``dProtAut`` and the registered
    events (``xContEv``). The DTE in the container never replaces the signed
    XML the platform keeps.
    """

    cdc: str
    request_xml: str
    response_raw: str
    result_code: str | None
    result_message: str | None
    status: str
    content_xml: str | None
    processed_at: datetime | None
    container: DocumentContainer | None = None

    @property
    def protocol(self) -> str | None:
        return self.container.protocol if self.container is not None else None

    @property
    def cancelled(self) -> bool:
        """Whether ``xContEv`` holds a registered cancellation of the CDC."""

        return self.container is not None and self.container.has_cancellation(
            self.cdc
        )


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


class KilaSifenQueryGateway:
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
        if not _es_cdc_valido(cdc):
            raise ValueError("El CDC debe tener exactamente 44 digitos numericos")
        request = REnviConsDeRequest(dId=_generate_query_id(), dCDC=cdc)

        def send(consulta) -> tuple[str, bytes, REnviConsDeResponse]:
            request_xml = consulta._serialize(request)
            body = consulta._send_raw_xml("cons_de", request_xml)
            return request_xml, body, consulta._como_respuesta(
                body, REnviConsDeResponse
            )

        request_xml, body, response = self._run_consulta(
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            operation=send,
        )
        status = _document_query_status(response.dCodRes)
        return DocumentQueryOutcome(
            cdc=cdc,
            request_xml=request_xml,
            response_raw=body.decode("utf-8", errors="replace"),
            result_code=response.dCodRes,
            result_message=response.dMsgRes,
            status=status,
            content_xml=response.xContenDE,
            processed_at=parse_sifen_datetime(response.dFecProc),
            container=read_document_container(body)
            if status == QUERY_FOUND
            else None,
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


def _document_query_status(code: str | None) -> str:
    if code == QUERY_FOUND_CODE:
        return QUERY_FOUND
    if code == QUERY_NOT_FOUND_OR_NOT_APPROVED_CODE:
        return QUERY_NOT_FOUND_OR_NOT_APPROVED
    # 0421 is "RUC Certificado sin permiso" in MT v150 Tabla G (p. 51) and
    # "CDC encontrado" in §12.3.4.3 (p. 157): NO DETERMINADO, read as error.
    return QUERY_ERROR


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
