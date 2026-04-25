"""Event domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Event:
    """A persisted fiscal event linked to one emitter/document."""

    id: str
    emitter_id: str
    document_id: str | None
    event_type: str
    input_payload: dict | None
    generated_xml: str | None
    signed_xml: str | None
    sifen_request_xml: str | None
    sifen_response_raw: str | None
    status: str
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime
