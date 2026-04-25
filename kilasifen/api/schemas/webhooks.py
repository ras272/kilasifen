"""Pydantic schemas for webhook APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WebhookEndpointCreateRequest(BaseModel):
    """Webhook endpoint creation payload."""

    url: HttpUrl
    secret: str = Field(min_length=6, max_length=255)
    event_subscriptions: list[str] | None = None
    retry_policy: dict[str, Any] | None = None


class WebhookEndpointResponse(BaseModel):
    """Webhook endpoint response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str | None
    url: str
    event_subscriptions: list[str] | None
    is_active: bool
    retry_policy: dict[str, Any] | None
    secret_preview: str
    created_at: datetime
    updated_at: datetime


class WebhookReplayRequest(BaseModel):
    """Replay request payload."""

    event_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class WebhookDeliveryResponse(BaseModel):
    """Webhook delivery response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    webhook_endpoint_id: str
    event_type: str
    payload_snapshot: dict[str, Any] | None
    attempt_number: int
    request_at: datetime | None
    response_code: int | None
    response_body_snapshot: str | None
    final_status: str
    created_at: datetime
    updated_at: datetime
