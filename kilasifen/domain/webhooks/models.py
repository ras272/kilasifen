"""Webhook domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class WebhookEndpoint:
    """A webhook endpoint configured for one emitter."""

    id: str
    emitter_id: str | None
    url: str
    secret_encrypted: str
    event_subscriptions: list[str] | None
    is_active: bool
    retry_policy: dict | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class WebhookDelivery:
    """One delivery attempt for a webhook event."""

    id: str
    webhook_endpoint_id: str
    event_type: str
    payload_snapshot: dict | None
    attempt_number: int
    request_at: datetime | None
    response_code: int | None
    response_body_snapshot: str | None
    final_status: str
    created_at: datetime
    updated_at: datetime
