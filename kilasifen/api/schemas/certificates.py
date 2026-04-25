"""Pydantic schemas for certificate APIs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CertificateResponse(BaseModel):
    """Certificate metadata returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    logical_name: str
    fingerprint: str | None
    serial_number: str | None
    subject_summary: str | None
    detected_ruc: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime
