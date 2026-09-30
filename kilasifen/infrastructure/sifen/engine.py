"""Emission engine adapters built on top of kilasifen.engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine import PRODUCCION, TEST, sign_xml
from kilasifen.engine.sdk.client import SifenClient
from kilasifen.engine.sdk.errors import (
    SifenTimeoutError,
    SifenTransportError,
    SifenValidationError,
)
from kilasifen.engine.transmissao.de import _build_enviar_de_request_xml
from kilasifen.infrastructure.kude.xml_qr_injector import apply_real_qr_to_signed_xml
from kilasifen.infrastructure.sifen.mapper import PysifenPayloadMapper


@dataclass(slots=True)
class EmissionOutcome:
    """Normalized result from a document emission attempt."""

    generated_xml: str | None
    signed_xml: str
    request_xml: str | None
    response_raw: str | None
    sifen_status: str
    result_code: str | None
    result_message: str | None
    cdc: str | None = None


@dataclass(slots=True)
class SubmissionOutcome:
    """Normalized result returned by a SIFEN document transport."""

    response_raw: str | None
    sifen_status: str
    result_code: str | None
    result_message: str | None


class EmissionTransportUncertainError(RuntimeError):
    """Transport failed after a stable fiscal payload had been prepared."""

    def __init__(
        self,
        message: str,
        *,
        generated_xml: str,
        signed_xml: str,
        request_xml: str,
        cdc: str,
    ) -> None:
        super().__init__(message)
        self.generated_xml = generated_xml
        self.signed_xml = signed_xml
        self.request_xml = request_xml
        self.cdc = cdc


class DocumentEmissionEngine(Protocol):
    """Contract for document emission engines."""

    def emit_document(
        self,
        *,
        document: Document,
        emitter: Emitter,
        certificate: Certificate,
        certificate_bytes: bytes,
        certificate_password: str,
        stamping: Stamping,
    ) -> EmissionOutcome:
        """Emit one document and return normalized artifacts."""


class DocumentSubmissionTransport(Protocol):
    """Transport boundary used after XML generation and signing."""

    def submit(
        self,
        *,
        signed_xml: str,
        tax_environment: str,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        """Submit signed XML and return a normalized SIFEN outcome."""


class PysifenDocumentTransport:
    """Live document transport backed by ``kilasifen.engine``."""

    def __init__(self) -> None:
        self.serializer = XmlSerializer(
            config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
        )

    def submit(
        self,
        *,
        signed_xml: str,
        tax_environment: str,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        ambiente = TEST if tax_environment == "test" else PRODUCCION
        with SifenClient(
            ambiente=ambiente,
            pkcs12_data=certificate_bytes,
            pkcs12_password=certificate_password,
            max_retries=0,
        ) as client:
            response = client.enviar_de_xml(signed_xml)

        result_code, result_message, status = _normalize_response(response)
        return SubmissionOutcome(
            response_raw=self.serializer.render(response),
            sifen_status=status,
            result_code=result_code,
            result_message=result_message,
        )


class PysifenEmissionEngine:
    """Concrete emission engine backed by kilasifen.engine transport and signing."""

    def __init__(
        self,
        mapper: PysifenPayloadMapper | None = None,
        deployment_environment: str = "test",
        transport: DocumentSubmissionTransport | None = None,
    ):
        self.mapper = mapper or PysifenPayloadMapper()
        self.deployment_environment = deployment_environment
        self.transport = transport or PysifenDocumentTransport()

    def emit_document(
        self,
        *,
        document: Document,
        emitter: Emitter,
        certificate: Certificate,
        certificate_bytes: bytes,
        certificate_password: str,
        stamping: Stamping,
    ) -> EmissionOutcome:
        del certificate
        _require_deployment_environment(emitter, self.deployment_environment)
        emission_input = self.mapper.map_document(
            document,
            emitter=emitter,
            stamping=stamping,
        )
        if emission_input.signed_xml:
            signed_xml = emission_input.signed_xml
            generated_xml = emission_input.generated_xml or emission_input.signed_xml
        else:
            if not emission_input.generated_xml or not emission_input.doc_id:
                raise SifenValidationError(
                    "document payload must include generated_xml and doc_id"
                )
            generated_xml = emission_input.generated_xml
            signed_xml = sign_xml(
                generated_xml,
                certificate_bytes,
                certificate_password,
                emission_input.doc_id,
            )
            signed_xml = apply_real_qr_to_signed_xml(signed_xml, emitter=emitter)

        request_xml = _build_enviar_de_request_xml(1, signed_xml).decode("utf-8")

        try:
            submission = self.transport.submit(
                signed_xml=signed_xml,
                tax_environment=emitter.tax_environment,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
            )
        except (SifenTimeoutError, SifenTransportError) as exc:
            raise EmissionTransportUncertainError(
                str(exc),
                generated_xml=generated_xml,
                signed_xml=signed_xml,
                request_xml=request_xml,
                cdc=emission_input.doc_id or "",
            ) from exc

        return EmissionOutcome(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            request_xml=request_xml,
            response_raw=submission.response_raw,
            sifen_status=submission.sifen_status,
            result_code=submission.result_code,
            result_message=submission.result_message,
            cdc=emission_input.doc_id,
        )


def _normalize_response(response) -> tuple[str | None, str | None, str]:
    result_code = None
    result_message = None
    status = "submitted"

    prot = (
        getattr(response, "rProtDe", None)
        or getattr(response, "gRespProc", None)
        or response
    )
    result_node = _first_result_node(prot)
    for attr in ("dCodRes", "dCodResLot", "dCodResC"):
        value = getattr(result_node, attr, None) or getattr(prot, attr, None)
        if value:
            result_code = str(value)
            break
    for attr in ("dMsgRes", "dMsgResLot", "dMsgResC"):
        value = getattr(result_node, attr, None) or getattr(prot, attr, None)
        if value:
            result_message = str(value)
            break

    status_text = str(getattr(prot, "dEstRes", "") or "").strip().lower()
    if result_code == "0260" or status_text == "aprobado":
        status = "approved"
    elif result_code or status_text == "rechazado":
        status = "rejected"

    return result_code, result_message, status


def _require_deployment_environment(emitter: Emitter, expected: str) -> None:
    if emitter.tax_environment != expected:
        raise SifenValidationError(
            "Emitter tax environment does not match this deployment"
        )


def _first_result_node(prot):
    result = getattr(prot, "gResProc", None)
    if isinstance(result, list):
        return result[0] if result else prot
    return result or prot
