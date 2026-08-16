"""Bounded, SSRF-resistant HTTP webhook delivery utilities."""

from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from kilasifen.infrastructure.webhooks.security import (
    ResolvedWebhookTarget,
    UnsafeWebhookUrlError,
    WebhookUrlPolicy,
    build_signature,
)

MAX_REQUEST_BODY_BYTES = 256 * 1024
MAX_RESPONSE_BODY_BYTES = 64 * 1024
MAX_RESPONSE_SNAPSHOT_CHARS = 2048
_REDACTED = "[REDACTED]"
_TRUNCATION_SUFFIX = "...[truncated]"
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|token|secret|password|passwd|api[_-]?key|csc|certificate)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(authorization|cookie|token|secret|password|passwd|api[_-]?key|csc)"
    r"(\s*[:=]\s*)([^,;\r\n]+)"
)


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
    """Send exact, version-signed payloads through a pinned-IP connection."""

    def __init__(
        self,
        sender: WebhookSender | None = None,
        timeout: float = 5.0,
        *,
        url_policy: WebhookUrlPolicy | None = None,
        response_body_limit: int = MAX_RESPONSE_BODY_BYTES,
    ) -> None:
        self.sender = sender
        self.timeout = timeout
        self.url_policy = url_policy or WebhookUrlPolicy()
        self.response_body_limit = response_body_limit

    def deliver(
        self,
        *,
        url: str,
        secret: str,
        event_type: str,
        delivery_id: str,
        payload_snapshot: dict | None,
        request_body: str | None = None,
    ) -> DeliveryOutcome:
        body = request_body or serialize_webhook_body(payload_snapshot)
        body_bytes = body.encode("utf-8")
        request_at = datetime.now(UTC)
        if len(body_bytes) > MAX_REQUEST_BODY_BYTES:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=None,
                response_body_snapshot="request_body_too_large",
                final_status="failed",
                retryable=False,
            )

        try:
            target = self.url_policy.resolve(url)
        except UnsafeWebhookUrlError:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=None,
                response_body_snapshot="unsafe_webhook_target",
                final_status="failed",
                retryable=False,
            )

        timestamp = str(int(request_at.timestamp()))
        signature = build_signature(
            secret=secret,
            timestamp=timestamp,
            delivery_id=delivery_id,
            event_type=event_type,
            body=body_bytes,
        )
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "KilaSifen-Webhook/1",
            "X-Kila-Signature-Version": "v1",
            "X-Kila-Timestamp": timestamp,
            "X-Kila-Event": event_type,
            "X-Kila-Delivery-ID": delivery_id,
            "X-Kila-Signature": signature,
        }
        try:
            if self.sender is not None:
                result = self.sender(
                    url=url,
                    body=body,
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                result = _send_pinned(
                    target=target,
                    body=body_bytes,
                    headers=headers,
                    timeout=self.timeout,
                    response_body_limit=self.response_body_limit,
                )
        except Exception:
            return DeliveryOutcome(
                request_at=request_at,
                response_code=None,
                response_body_snapshot="transport_error",
                final_status="retry_pending",
                retryable=True,
            )

        if result is None:
            status_code, response_text = 200, ""
        else:
            status_code, response_text = result
        snapshot = sanitize_response_snapshot(response_text)
        if 200 <= status_code < 300:
            return DeliveryOutcome(
                request_at, status_code, snapshot, "delivered", False
            )
        if status_code in {408, 425, 429} or status_code >= 500:
            return DeliveryOutcome(
                request_at, status_code, snapshot, "retry_pending", True
            )
        return DeliveryOutcome(request_at, status_code, snapshot, "failed", False)


def serialize_webhook_body(payload_snapshot: dict | None) -> str:
    """Serialize the persisted envelope once using the public canonical format."""

    return json.dumps(payload_snapshot or {}, separators=(",", ":"), sort_keys=True)


def sanitize_response_snapshot(response_text: str) -> str:
    """Redact common credentials and persist only a bounded diagnostic sample."""

    try:
        value = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        raw = response_text[: MAX_RESPONSE_SNAPSHOT_CHARS + 1]
        snapshot = _SENSITIVE_TEXT.sub(rf"\1\2{_REDACTED}", raw)
    else:
        snapshot = json.dumps(
            _redact_value(value), separators=(",", ":"), sort_keys=True
        )
    if len(snapshot) > MAX_RESPONSE_SNAPSHOT_CHARS:
        content_limit = MAX_RESPONSE_SNAPSHOT_CHARS - len(_TRUNCATION_SUFFIX)
        return f"{snapshot[:content_limit]}{_TRUNCATION_SUFFIX}"
    if len(response_text) > MAX_RESPONSE_SNAPSHOT_CHARS:
        content_limit = MAX_RESPONSE_SNAPSHOT_CHARS - len(_TRUNCATION_SUFFIX)
        return f"{snapshot[:content_limit]}{_TRUNCATION_SUFFIX}"
    return snapshot


def _redact_value(value):
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _SENSITIVE_KEY.search(str(key)) else _redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _send_pinned(
    *,
    target: ResolvedWebhookTarget,
    body: bytes,
    headers: dict[str, str],
    timeout: float,
    response_body_limit: int,
) -> tuple[int, str]:
    connection_type = (
        _PinnedHTTPSConnection if target.scheme == "https" else _PinnedHTTPConnection
    )
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    for pinned_ip in target.ip_addresses:
        connection = connection_type(
            hostname=target.hostname,
            port=target.port,
            pinned_ip=pinned_ip,
            timeout=_remaining_timeout(deadline),
        )
        try:
            connection.request(
                "POST",
                target.request_target,
                body=body,
                headers=headers,
            )
            _apply_remaining_socket_timeout(connection, deadline)
            response = connection.getresponse()
            chunks: list[bytes] = []
            remaining_bytes = response_body_limit + 1
            while remaining_bytes > 0:
                _apply_remaining_socket_timeout(connection, deadline)
                chunk = response.read(min(8192, remaining_bytes))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining_bytes -= len(chunk)
            response_body = b"".join(chunks)
            if len(response_body) > response_body_limit:
                response_body = response_body[:response_body_limit] + b"...[truncated]"
            return response.status, response_body.decode("utf-8", errors="replace")
        except OSError as exc:
            last_error = exc
        finally:
            connection.close()
    if last_error is not None:
        raise last_error
    raise OSError("no validated webhook address available")


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("webhook request deadline exceeded")
    return remaining


def _apply_remaining_socket_timeout(
    connection: http.client.HTTPConnection,
    deadline: float,
) -> None:
    if connection.sock is None:
        raise OSError("webhook connection is not open")
    connection.sock.settimeout(_remaining_timeout(deadline))


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to a validated IP while retaining the original HTTP Host."""

    def __init__(
        self, *, hostname: str, port: int, pinned_ip: str, timeout: float
    ) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    """Pinned TCP connection with normal CA and hostname verification."""

    def __init__(
        self, *, hostname: str, port: int, pinned_ip: str, timeout: float
    ) -> None:
        super().__init__(
            hostname=hostname,
            port=port,
            pinned_ip=pinned_ip,
            timeout=timeout,
        )
        self._context = ssl.create_default_context()

    def connect(self) -> None:
        super().connect()
        assert self.sock is not None
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
