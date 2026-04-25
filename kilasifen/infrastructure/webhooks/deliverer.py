"""HTTP webhook delivery utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Callable

import httpx


WebhookSender = Callable[..., tuple[int, str] | None]


@dataclass(slots=True)
class DeliveryOutcome:
    """Normalized result of one webhook HTTP call."""

    request_at: datetime
    response_code: int | None
    response_body_snapshot: str | None
    final_status: str
    retryable: bool


class WebhookDeliverer:
    """Send signed webhook payloads to configured endpoints."""

    def __init__(self, sender: WebhookSender | None = None, timeout: float = 10.0):
        self.sender = sender or _default_sender
        self.timeout = timeout

    def deliver(
        self,
        *,
        url: str,
        secret: str,
        event_type: str,
        delivery_id: str,
        payload_snapshot: dict | None,
    ) -> DeliveryOutcome:
        body = json.dumps(payload_snapshot or {}, separators=(",", ":"), sort_keys=True)
        signature = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Kila-Event": event_type,
            "X-Kila-Delivery-ID": delivery_id,
            "X-Kila-Signature": f"sha256={signature}",
        }
        request_at = datetime.now(UTC)
        try:
            result = self.sender(url=url, body=body, headers=headers, timeout=self.timeout)
        except Exception as exc:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=None,
                response_body_snapshot=str(exc),
                final_status="retry_pending",
                retryable=True,
            )

        if result is None:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=200,
                response_body_snapshot="",
                final_status="delivered",
                retryable=False,
            )

        status_code, response_text = result
        if 200 <= status_code < 300:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=status_code,
                response_body_snapshot=response_text,
                final_status="delivered",
                retryable=False,
            )
        if status_code >= 500:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=status_code,
                response_body_snapshot=response_text,
                final_status="retry_pending",
                retryable=True,
            )
        return DeliveryOutcome(
            request_at=request_at,
            response_code=status_code,
            response_body_snapshot=response_text,
            final_status="failed",
            retryable=False,
        )


def _default_sender(*, url: str, body: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    response = httpx.post(url, content=body, headers=headers, timeout=timeout)
    return response.status_code, response.text
