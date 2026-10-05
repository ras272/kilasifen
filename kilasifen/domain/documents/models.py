"""Document domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Document:
    """A persisted fiscal document.

    ``sifen_approved_at`` is when SIFEN approved the DE: ``dFecProc`` of a
    synchronous answer, or a lower bound of it when the approval was learnt
    by query (``dFecFirma`` of the signed DE). The cancellation window counts
    from it (MT v150 §6.2.1 p. 25). ``sifen_protocol`` is ``dProtAut`` and
    ``sifen_messages`` every ``gResProc`` of the last answer, as
    ``{"code", "message"}`` items. ``retryable_server_error`` marks a
    rejection with 0161/0162 whose signed XML is sent again. ``timbrado`` is
    the ``dNumTim`` the signed DE carries.
    """

    id: str
    emitter_id: str
    external_id: str | None
    idempotency_key: str | None
    document_type: str
    payload_snapshot: dict | None
    generated_xml: str | None
    signed_xml: str | None
    sifen_request_xml: str | None
    sifen_response_raw: str | None
    last_query_request_xml: str | None
    last_query_response_raw: str | None
    last_query_at: datetime | None
    cdc: str | None
    internal_status: str
    sifen_status: str | None
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime
    establishment: str | None = None
    point: str | None = None
    document_number: int | None = None
    sifen_approved_at: datetime | None = None
    sifen_protocol: str | None = None
    sifen_messages: list[dict] | None = None
    retryable_server_error: bool = False
    timbrado: str | None = None
    # dCodSeg (B004) chosen once at creation; every rebuild reuses it so the
    # CDC never changes (MT v150 §10.3 and §6.5). None for raw-XML documents.
    security_code: str | None = None
    # Codes of fiscal warnings found at creation, such as an emission date
    # that makes the transmission extemporaneous (1005).
    fiscal_warnings: tuple[str, ...] = ()
