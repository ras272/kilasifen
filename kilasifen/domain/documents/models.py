"""Document domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Document:
    """A persisted fiscal document."""

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
    cdc: str | None
    internal_status: str
    sifen_status: str | None
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime
