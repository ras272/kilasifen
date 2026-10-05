"""Emission engine adapters built on top of kilasifen.engine.

Emitting a document takes two separate steps so the platform can make the
exact payload durable before anything reaches SIFEN:

1. :meth:`DocumentEmissionEngine.prepare_document` builds and signs the DE
   and wraps it in the ``rEnviDe`` request that will travel, with its real
   ``dId``. It never touches the network.
2. :meth:`DocumentEmissionEngine.submit_prepared` sends that request
   unchanged and normalizes the answer.

Between both steps the worker commits the prepared request, so a crash, a
timeout or an unreadable answer can always be reconciled by CDC. A document
that SIFEN may receive again (a request that never left, a CDC SIFEN reported
as not approved, a 0161/0162 server failure) travels again through
:meth:`DocumentEmissionEngine.wrap_signed_document`: the same signed ``rDE``
in a new ``rEnviDe`` with a fresh ``dId``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kilasifen.config import get_settings
from kilasifen.domain.common.paraguay_time import paraguay_now, to_paraguay_wall_time
from kilasifen.domain.common.sifen_results import classify_reception
from kilasifen.domain.documents.fiscal_dates import transmission_warnings
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine import PRODUCCION, TEST, TransmisionDE, sign_xml
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.transmision.base import _generate_id
from kilasifen.engine.transmision.de import _build_enviar_de_request_xml
from kilasifen.infrastructure.kude.xml_qr_injector import apply_real_qr_to_signed_xml
from kilasifen.infrastructure.sifen.mapper import KilaSifenPayloadMapper
from kilasifen.infrastructure.sifen.responses import (
    SifenMessage,
    read_reception_answer,
)
from kilasifen.infrastructure.sifen.signing_checks import assert_ready_to_sign

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedSubmission:
    """Signed document and the exact ``rEnviDe`` request that carries it."""

    generated_xml: str
    signed_xml: str
    request_xml: str
    cdc: str


@dataclass(slots=True)
class SubmissionOutcome:
    """Normalized result returned by a SIFEN document transport.

    ``sifen_status`` is ``approved``, ``approved_with_observation``,
    ``rejected`` or ``unknown`` (an answer the platform cannot classify, to be
    reconciled by CDC). ``protocol`` is ``dProtAut``, ``processed_at`` is
    ``dFecProc`` and ``messages`` holds every ``gResProc``.
    """

    response_raw: str | None
    sifen_status: str
    result_code: str | None
    result_message: str | None
    protocol: str | None = None
    processed_at: datetime | None = None
    messages: tuple[SifenMessage, ...] = ()


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

    def wrap_signed_document(self, *, signed_xml: str) -> str:
        """Wrap an already signed ``rDE`` in a new ``rEnviDe`` (fresh ``dId``).

        Used to send the same document again: never re-signs, never
        contacts SIFEN.
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
        return outcome_from_reception_body(body)


class KilaSifenEmissionEngine:
    """Concrete emission engine backed by kilasifen.engine transport and signing."""

    def __init__(
        self,
        mapper: KilaSifenPayloadMapper | None = None,
        deployment_environment: str = "test",
        transport: DocumentSubmissionTransport | None = None,
        clock: Callable[[], datetime] = paraguay_now,
    ):
        # Without an explicit mapper the dNomEmi literal of the test
        # environment comes from KILA_SIFEN_TEST_EMITTER_NAME_LITERAL (F13).
        self.mapper = mapper or KilaSifenPayloadMapper(
            test_emitter_name_literal=get_settings().test_emitter_name_literal
        )
        self.clock = clock
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
        now = self.clock()
        # dFecFirma is the real signing time (MT v150 A004; RG 23/2019 Art. 13):
        # the typed builder writes it right before the signature below.
        emission_input = self.mapper.map_document(
            document,
            emitter=emitter,
            stamping=stamping,
            signed_at=to_paraguay_wall_time(now),
        )
        if emission_input.signed_xml:
            # XML the platform signed in an earlier attempt travels unchanged
            # and keeps its dFecFirma: it is never signed again.
            signed_xml = emission_input.signed_xml
            generated_xml = emission_input.generated_xml or emission_input.signed_xml
        else:
            if not emission_input.generated_xml or not emission_input.doc_id:
                raise SifenValidationError(
                    "document payload must include generated_xml and doc_id"
                )
            generated_xml = emission_input.generated_xml
            dates = assert_ready_to_sign(
                generated_xml,
                now=now,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
            )
            _log_extemporaneous_transmission(
                document, emission=dates.emission, signed_at=dates.signature, now=now
            )
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

        return PreparedSubmission(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            request_xml=self.wrap_signed_document(signed_xml=signed_xml),
            cdc=emission_input.doc_id,
        )

    def wrap_signed_document(self, *, signed_xml: str) -> str:
        # The dId rules (unique? sequential? validated?) are NO DETERMINADO:
        # MT v150 only calls it "autoincremental" and no rejection code uses
        # it. A new one per request never reuses a dId that reached SIFEN.
        return _build_enviar_de_request_xml(_generate_id(), signed_xml).decode(
            "utf-8"
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


def outcome_from_reception_body(body: bytes | str) -> SubmissionOutcome:
    """Classify a siRecepDE answer (DECISIONES F60).

    ``dEstRes`` decides, normalized (MT v150 §9.1.3 PP050 p. 46, cap. 12
    p. 145); without it only 0260 proves an approval and anything else is
    ``unknown``. The reported code and message are those of the first
    ``gResProc`` (the first error of a rejection, Dto 872/2023 Art. 29).

    Raises:
        SifenUnexpectedResponseError: if ``body`` is not an ``rRetEnviDe``.
    """

    answer = read_reception_answer(body)
    first = answer.messages[0] if answer.messages else None
    raw = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    return SubmissionOutcome(
        response_raw=raw,
        sifen_status=classify_reception(answer.state_text, answer.codes).value,
        result_code=first.code if first else None,
        result_message=first.message if first else None,
        protocol=answer.protocol,
        processed_at=answer.processed_at,
        messages=answer.messages,
    )


def _log_extemporaneous_transmission(
    document: Document, *, emission: datetime, signed_at: datetime, now: datetime
) -> None:
    """Warn when SIFEN will approve with observation 1005 (MT v150 §6.2.1)."""

    warnings = transmission_warnings(emission=emission, signed_at=signed_at, now=now)
    if warnings:
        logger.warning(
            "documents.transmission.extemporaneous",
            extra={"document_id": document.id, "fiscal_warnings": warnings},
        )


def _require_deployment_environment(emitter: Emitter, expected: str) -> None:
    if emitter.tax_environment != expected:
        raise SifenValidationError(
            "Emitter tax environment does not match this deployment"
        )
