"""Pydantic schemas for webhook APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class WebhookRetryPolicy(BaseModel):
    """Bounded automatic retry policy for one endpoint."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=5, ge=1, le=8)


class WebhookEndpointCreateRequest(BaseModel):
    """Webhook endpoint creation payload."""

    url: HttpUrl
    secret: str = Field(min_length=32, max_length=255)
    event_subscriptions: list[str] | None = None
    retry_policy: WebhookRetryPolicy | None = None


class WebhookEndpointUpdateRequest(BaseModel):
    """Partial, secret-safe update for a webhook endpoint."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl | None = None
    secret: str | None = Field(default=None, min_length=32, max_length=255)
    event_subscriptions: list[str] | None = None
    retry_policy: WebhookRetryPolicy | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_one_change(self) -> "WebhookEndpointUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one webhook field must be provided")
        non_nullable = {"url", "secret", "retry_policy", "is_active"}
        null_fields = non_nullable.intersection(self.model_fields_set)
        if any(getattr(self, field) is None for field in null_fields):
            raise ValueError("url, secret, retry_policy and is_active cannot be null")
        return self


class WebhookEndpointResponse(BaseModel):
    """Webhook endpoint response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str | None
    url: str
    event_subscriptions: list[str] | None
    is_active: bool
    retry_policy: dict[str, Any] | None
    secret_configured: bool
    created_at: datetime
    updated_at: datetime


class WebhookReplayRequest(BaseModel):
    """Replay of an existing delivery; the event content is never caller-made."""

    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "ID de una entrega ya generada para un endpoint de este emisor. "
            "Se reenvían su tipo, data y occurred_at con un delivery ID nuevo."
        ),
    )


class WebhookDeliveryResponse(BaseModel):
    """Webhook delivery response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    webhook_endpoint_id: str
    event_type: str
    payload_snapshot: dict[str, Any] | None
    request_body: str | None
    attempt_number: int
    request_at: datetime | None
    response_code: int | None
    response_body_snapshot: str | None
    final_status: str
    created_at: datetime
    updated_at: datetime
