"""What SIFEN's answer to a query by CDC means for a document.

Shared by the emission worker and the reconcile endpoint (DECISIONES F61,
F62, F63):

- 0422: the CDC is a DTE. The document is approved, or cancelled when
  ``xContEv`` holds a registered cancellation (MT v150 §9.4.3 pp. 51-52). The
  DTE in the container never replaces the signed XML the platform keeps
  (Dto 872/2023 Art. 44 asks to keep the documents issued).
- 0420: "no existe o no esta aprobado" (Guia de Mejores Practicas DNIT
  oct-2024 p. 12). A rejection 1001/1002 waiting for this query is now
  final; otherwise the same signed DE may be sent again with its CDC (Dto
  872/2023 Art. 29; MT v150 §6.5 pp. 26-27). The Guia asks to check first that
  no lot in process holds the CDC: the platform never sends lots, so none
  can.
"""

from __future__ import annotations

from dataclasses import replace

from kilasifen.domain.common.fiscal_states import (
    DOCUMENT_APPROVED_STATUSES,
    DOCUMENT_CANCELLED_STATUS,
)
from kilasifen.domain.common.sifen_results import DUPLICATE_DOCUMENT_CODES
from kilasifen.domain.documents.models import Document
from kilasifen.infrastructure.sifen.de_facts import approval_lower_bound
from kilasifen.infrastructure.sifen.query import DocumentQueryOutcome


def document_found_at_sifen(
    document: Document,
    outcome: DocumentQueryOutcome,
) -> Document:
    """Record that the CDC is a DTE (0422), possibly already cancelled.

    A query carries no approval time, so the cancellation window keeps
    counting from a lower bound of the approval (DECISIONES F71).
    """

    if outcome.cancelled:
        status = DOCUMENT_CANCELLED_STATUS
    elif document.internal_status in DOCUMENT_APPROVED_STATUSES:
        status = document.internal_status
    else:
        status = "approved"
    return replace(
        document,
        internal_status=status,
        sifen_status=status,
        sifen_protocol=outcome.protocol or document.sifen_protocol,
        sifen_approved_at=document.sifen_approved_at or approval_lower_bound(document),
        retryable_server_error=False,
    )


def document_not_approved_at_sifen(document: Document) -> Document:
    """Record that SIFEN holds no approved DTE for the CDC (0420).

    Returns the document ``rejected`` when it was waiting on this query to
    believe a 1001/1002 rejection, else ``queued`` so that the same signed
    DE is sent again.
    """

    duplicate = pending_duplicate_rejection(document)
    if duplicate is not None:
        return replace(
            document,
            internal_status="rejected",
            sifen_status="rejected",
            sifen_result_code=duplicate.get("code"),
            sifen_result_message=duplicate.get("message"),
            retryable_server_error=False,
        )
    return replace(document, internal_status="queued", sifen_status="queued")


def pending_duplicate_rejection(document: Document) -> dict | None:
    """The rejection of the last answer, if it lists 1001 or 1002.

    MT v150 §12.4 val. 2-3 (p. 159): both codes only fire when another
    document is already AUTHORIZED, so they are believed only after the CDC
    is queried (DECISIONES F61). The order of ``gResProc`` is NO
    DETERMINADO, so every message is checked; the first one, the error
    SIFEN reports (Dto 872/2023 Art. 29), is returned.
    """

    messages = _messages(document)
    if any(message.get("code") in DUPLICATE_DOCUMENT_CODES for message in messages):
        return messages[0]
    return None


def answer_codes(document: Document) -> frozenset[str]:
    """Every result code of the last siRecepDE answer kept on ``document``.

    The order of ``gResProc`` (0-100, XSD protProcesDE_v150.xsd) is NO
    DETERMINADO, so a rule that depends on one code checks all of them.
    """

    codes = {
        str(message["code"]) for message in _messages(document) if message.get("code")
    }
    if document.sifen_result_code:
        codes.add(document.sifen_result_code)
    return frozenset(codes)


def answer_messages(document: Document) -> tuple[tuple[str, str | None], ...]:
    """``(code, message)`` of every ``gResProc`` of the last siRecepDE answer."""

    pairs = [
        (str(message["code"]), message.get("message"))
        for message in _messages(document)
        if message.get("code")
    ]
    if document.sifen_result_code and not pairs:
        pairs.append((document.sifen_result_code, document.sifen_result_message))
    return tuple(pairs)


def _messages(document: Document) -> list[dict]:
    return [
        message
        for message in document.sifen_messages or []
        if isinstance(message, dict)
    ]
