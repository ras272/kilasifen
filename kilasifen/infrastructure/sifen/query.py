"""Read-side SIFEN query adapters built on top of kilasifen.engine.

A query by CDC (siConsDE) is read by its code (DECISIONES F62): 0422 means
the CDC is an approved DTE and ``xContenDE`` carries the container
``rContDe{rDE, dProtAut, xContEv}`` (MT v150 Tabla G p. 51, Schemas XML 11-12
pp. 51-52); 0420 means "no existe o no esta aprobado" (Guia de Mejores
Practicas DNIT oct-2024 p. 12); any other code (0421, 01xx, 0380) is an
error, never a "not found". The request stored for audit is the exact text
that travelled, with its real ``dId``.

A RUC query (siConsRUC) is ``found`` when SIFEN returns the taxpayer
(``xContRUC``, 0502), ``not_found`` only for 0500 (RUC inexistente) and
``error`` for any other code, such as 0501 (MT v150 §9.6.2, Tabla H). The
answer carries RUC, razon social, state and the electronic-invoicer flag
(Schema ``WS_SiConsRUC_v141.xsd``), never the DV, which is computed here with
the official modulo 11 routine. A lone 0160 without validation detail, or a
0161/0162, is asked again after a short pause: the SIFEN test environment sent
that 0160 to four identical valid RUC queries in a row (DECISIONES F67).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.common.sifen_results import (
    QUERY_FOUND_CODE,
    QUERY_NOT_FOUND_OR_NOT_APPROVED_CODE,
    is_retryable_rejection,
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
from kilasifen.engine.sdk.errors import (
    SifenUnexpectedResponseError,
    SifenValidationError,
)
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv
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

#: ``RucQueryOutcome.status`` values.
RUC_FOUND = "found"
RUC_NOT_FOUND = "not_found"
RUC_ERROR = "error"
#: siConsRUC "RUC inexistente" (MT v150 §9.6.2, Tabla H).
RUC_NOT_FOUND_CODE = "0500"
#: Pauses before asking siConsRUC again after a transient answer.
RUC_RETRY_PAUSES_SECONDS = (2.0, 4.0)


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
    #: Computed with the official modulo 11 routine; SIFEN does not return it.
    taxpayer_dv: str | None = None


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

    def __init__(
        self,
        deployment_environment: str = "test",
        *,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.deployment_environment = deployment_environment
        self.sleep = sleep
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
        response = self._ask_ruc(
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            ruc=ruc,
        )
        assert isinstance(response, RResEnviConsRuc)
        taxpayer = response.xContRUC
        taxpayer_ruc = getattr(taxpayer, "dRUCCons", None)
        return RucQueryOutcome(
            queried_ruc=normalized_ruc,
            request_xml=self.serializer.render(request),
            response_raw=self.serializer.render(response),
            result_code=response.dCodRes,
            result_message=response.dMsgRes,
            status=_ruc_query_status(response.dCodRes, taxpayer),
            taxpayer_ruc=taxpayer_ruc,
            taxpayer_legal_name=getattr(taxpayer, "dRazCons", None),
            taxpayer_state_code=getattr(taxpayer, "dCodEstCons", None),
            taxpayer_state=getattr(taxpayer, "dDesEstCons", None),
            electronic_taxpayer=_normalize_electronic_flag(
                getattr(taxpayer, "dRUCFactElec", None)
            ),
            taxpayer_dv=_ruc_dv(taxpayer_ruc),
        )

    def _ask_ruc(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        ruc: str,
    ) -> RResEnviConsRuc:
        """Ask siConsRUC, again after a pause while the answer is transient.

        The query has no fiscal effect, so repeating it is safe. Any other
        failure (timeout, cut connection, another code) is raised at once.
        """

        for pause in (*RUC_RETRY_PAUSES_SECONDS, None):
            try:
                return self._run_consulta(
                    emitter=emitter,
                    certificate_bytes=certificate_bytes,
                    certificate_password=certificate_password,
                    operation=lambda consulta: consulta.consultar_ruc(ruc),
                )
            except SifenUnexpectedResponseError as exc:
                if pause is None or not _transient_answer(exc):
                    raise
                self.sleep(pause)
        raise AssertionError("unreachable")

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


def _ruc_query_status(code: str | None, taxpayer: object | None) -> str:
    if taxpayer is not None:
        return RUC_FOUND
    if code == RUC_NOT_FOUND_CODE:
        return RUC_NOT_FOUND
    # 0501 (sin permiso para consultar) or any other code says nothing about
    # whether the RUC exists.
    return RUC_ERROR


def _ruc_dv(ruc: str | None) -> str | None:
    return str(calculate_mod11_dv(ruc)) if ruc else None


def _transient_answer(exc: SifenUnexpectedResponseError) -> bool:
    """A lone 0160 without validation detail, or 0161/0162."""

    return exc.code is not None and is_retryable_rejection(
        [(exc.code, exc.response_message)]
    )


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
