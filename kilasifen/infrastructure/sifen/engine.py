"""Emission engine adapters built on top of kilasifen.engine.

Emitting a document takes two separate steps so the platform can make the
exact payload durable before anything reaches SIFEN:

1. :meth:`DocumentEmissionEngine.prepare_document` builds and signs the DE
   and wraps it in the ``rEnviDe`` request that will travel, with its real
   ``dId``. It never touches the network.
2. :meth:`DocumentEmissionEngine.submit_prepared` sends that request
   unchanged and normalizes the answer.

Between both steps the worker commits the prepared request, so a crash, a
timeout or an unreadable answer can always be reconciled by CDC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine import PRODUCCION, TEST, TransmisionDE, sign_xml
from kilasifen.engine.de.bindings.v150.ws_si_recep_de_v150 import RRetEnviDe
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.transmision.base import _generate_id
from kilasifen.engine.transmision.de import _build_enviar_de_request_xml
from kilasifen.infrastructure.kude.xml_qr_injector import apply_real_qr_to_signed_xml
from kilasifen.infrastructure.sifen.mapper import KilaSifenPayloadMapper


@dataclass(frozen=True, slots=True)
class PreparedSubmission:
    """Signed document and the exact ``rEnviDe`` request that carries it."""

    generated_xml: str
    signed_xml: str
    request_xml: str
    cdc: str


@dataclass(slots=True)
class SubmissionOutcome:
    """Normalized result returned by a SIFEN document transport."""

    response_raw: str | None
    sifen_status: str
    result_code: str | None
    result_message: str | None


class DocumentEmissionEngine(Protocol):
    """Contract for document emission engines."""

    def prepare_document(
        self,
        *,
        document: Document,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        stamping: Stamping,
    ) -> PreparedSubmission:
        """Build, sign and wrap one document without contacting SIFEN.

        Raises:
            SifenValidationError: if the document cannot be emitted as is.
        """

    def submit_prepared(
        self,
        *,
        request_xml: str,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        """Send a prepared ``rEnviDe`` unchanged and normalize the answer.

        Any exception other than
        :class:`~kilasifen.engine.sdk.errors.SifenRequestNotSentError` leaves
        the outcome unknown: SIFEN may have processed the request.
        """


class DocumentSubmissionTransport(Protocol):
    """Transport boundary used after XML generation and signing."""

    def submit(
        self,
        *,
        request_xml: str,
        tax_environment: str,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        """Send a prepared ``rEnviDe`` and return a normalized SIFEN outcome."""


class KilaSifenDocumentTransport:
    """Live document transport backed by ``kilasifen.engine``."""

    def __init__(self) -> None:
        self.serializer = XmlSerializer(
            config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
        )

    def submit(
        self,
        *,
        request_xml: str,
        tax_environment: str,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        ambiente = TEST if tax_environment == "test" else PRODUCCION
        # The request travels byte for byte as persisted (same dId, same
        # signature). Only failures that prove nothing left are retried here.
        with TransmisionDE(
            ambiente=ambiente,
            pkcs12_data=certificate_bytes,
            pkcs12_password=certificate_password,
            max_retries=0,
        ) as transmision:
            body = transmision._send_raw_xml("recep_de", request_xml)
            response = transmision._como_respuesta(body, RRetEnviDe)

        result_code, result_message, status = _normalize_response(response)
        return SubmissionOutcome(
            response_raw=self.serializer.render(response),
            sifen_status=status,
            result_code=result_code,
            result_message=result_message,
        )


class KilaSifenEmissionEngine:
    """Concrete emission engine backed by kilasifen.engine transport and signing."""

    def __init__(
        self,
        mapper: KilaSifenPayloadMapper | None = None,
        deployment_environment: str = "test",
        transport: DocumentSubmissionTransport | None = None,
    ):
        self.mapper = mapper or KilaSifenPayloadMapper()
        self.deployment_environment = deployment_environment
        self.transport = transport or KilaSifenDocumentTransport()

    def prepare_document(
        self,
        *,
        document: Document,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        stamping: Stamping,
    ) -> PreparedSubmission:
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
        if not emission_input.doc_id:
            # Without a CDC a lost answer could never be reconciled.
            raise SifenValidationError("document payload must include doc_id")

        request_xml = _build_enviar_de_request_xml(_generate_id(), signed_xml)
        return PreparedSubmission(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            request_xml=request_xml.decode("utf-8"),
            cdc=emission_input.doc_id,
        )

    def submit_prepared(
        self,
        *,
        request_xml: str,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        return self.transport.submit(
            request_xml=request_xml,
            tax_environment=emitter.tax_environment,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
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
