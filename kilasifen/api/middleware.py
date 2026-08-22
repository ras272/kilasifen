"""Security middleware enforced before request parsing and authentication."""

from __future__ import annotations

import logging
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis as AsyncRedis
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from kilasifen.api.schemas.common import ErrorEnvelope, ErrorPayload
from kilasifen.config import Settings
from kilasifen.infrastructure.limits.redis import RedisRequestLimiter, RequestLease

logger = logging.getLogger(__name__)

_CERTIFICATE_UPLOAD_PARTS = ("emitters", "certificates")


class RequestBodyLimitMiddleware:
    """Reject oversized bodies at the ASGI receive boundary."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = request_body_limit(scope, self.settings)
        content_length = _content_length(scope)
        if content_length is not None and content_length > limit:
            await _send_error(
                scope,
                receive,
                send,
                status_code=413,
                code="request.body_too_large",
                message="Request body exceeds the configured size limit.",
                category="validation",
                details={"max_bytes": limit},
            )
            return

        received = 0
        response_started = False

        async def capped_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await _send_error(
                scope,
                receive,
                send,
                status_code=413,
                code="request.body_too_large",
                message="Request body exceeds the configured size limit.",
                category="validation",
                details={"max_bytes": limit},
            )


class PreAuthRateLimitMiddleware:
    """Apply a cheap network budget before expensive credential verification."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.identity_resolver = NetworkIdentityResolver(settings.trusted_proxy_cidrs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._must_limit(scope):
            await self.app(scope, receive, send)
            return

        redis = AsyncRedis.from_url(
            self.settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        limiter = RedisRequestLimiter(
            redis,
            requests_per_window=self.settings.pre_auth_rate_limit_requests,
            window_seconds=self.settings.rate_limit_window_seconds,
            max_concurrent=self.settings.pre_auth_max_concurrent_requests,
            lease_seconds=self.settings.request_lease_seconds,
        )
        identity = f"network:{self.identity_resolver.resolve(scope)}"
        lease: RequestLease | None = None
        try:
            try:
                lease = await limiter.acquire(identity)
            except Exception:
                await _send_error(
                    scope,
                    receive,
                    send,
                    status_code=503,
                    code="limits.backend_unavailable",
                    message="Request limiting is temporarily unavailable.",
                    category="service_unavailable",
                )
                return

            if not lease.acquired:
                await _send_error(
                    scope,
                    receive,
                    send,
                    status_code=429,
                    code=f"limits.pre_auth_{lease.reason}_exceeded",
                    message="Request limit exceeded. Retry later.",
                    category="rate_limit",
                    details={"retry_after_seconds": lease.retry_after_seconds},
                    headers={"Retry-After": str(lease.retry_after_seconds)},
                )
                return
            await self.app(scope, receive, send)
        finally:
            if lease is not None:
                try:
                    await limiter.release(lease)
                except Exception:
                    logger.exception("limits.pre_auth_lease_release_failed")
            try:
                await redis.aclose()
            except Exception:
                logger.exception("limits.pre_auth_redis_close_failed")

    def _must_limit(self, scope: Scope) -> bool:
        if scope["type"] != "http":
            return False
        if self.settings.environment not in {"staging", "production"}:
            return False
        if not self.settings.request_limits_enabled:
            return False
        path = str(scope.get("path", ""))
        public_probe_paths = {
            f"/{self.settings.api_version}/health",
            f"/{self.settings.api_version}/ready",
        }
        return path not in public_probe_paths


class NetworkIdentityResolver:
    """Resolve the client IP without trusting caller-controlled proxy headers."""

    def __init__(self, trusted_proxy_cidrs: list[str]) -> None:
        self._trusted_proxies = tuple(
            ip_network(value, strict=False) for value in trusted_proxy_cidrs
        )

    def resolve(self, scope: Scope) -> str:
        peer = _parse_peer(scope)
        if peer is None:
            return "unknown"
        if not self._is_trusted(peer):
            return peer.compressed

        forwarded = _forwarded_for(scope)
        if forwarded is None:
            return peer.compressed
        chain = (*forwarded, peer)
        for address in reversed(chain):
            if not self._is_trusted(address):
                return address.compressed
        return forwarded[0].compressed if forwarded else peer.compressed

    def _is_trusted(self, address: IPv4Address | IPv6Address) -> bool:
        return any(address in network for network in self._trusted_proxies)


class _RequestBodyTooLarge(Exception):
    pass


def request_body_limit(scope: Scope, settings: Settings) -> int:
    """Return the strict body cap for the resolved endpoint shape."""

    if _is_certificate_upload(scope, settings.api_version):
        return settings.max_pfx_upload_bytes + settings.multipart_body_overhead_bytes
    return settings.max_json_request_body_bytes


def _is_certificate_upload(scope: Scope, api_version: str) -> bool:
    if scope.get("method") != "POST":
        return False
    parts = tuple(part for part in str(scope.get("path", "")).split("/") if part)
    return (
        len(parts) == 4
        and parts[0] == api_version
        and parts[1] == _CERTIFICATE_UPLOAD_PARTS[0]
        and parts[3] == _CERTIFICATE_UPLOAD_PARTS[1]
    )


def _content_length(scope: Scope) -> int | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() != b"content-length":
            continue
        try:
            value = int(raw_value.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return None
        return value if value >= 0 else None
    return None


def _parse_peer(scope: Scope) -> IPv4Address | IPv6Address | None:
    client = scope.get("client")
    if client is None:
        return None
    try:
        return ip_address(client[0])
    except ValueError:
        return None


def _forwarded_for(
    scope: Scope,
) -> tuple[IPv4Address | IPv6Address, ...] | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() != b"x-forwarded-for":
            continue
        try:
            values = raw_value.decode("ascii").split(",")
            addresses = tuple(ip_address(value.strip()) for value in values)
        except (UnicodeDecodeError, ValueError):
            return None
        return addresses or None
    return None


async def _send_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    category: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    state = scope.setdefault("state", {})
    correlation_id = state.setdefault("correlation_id", str(uuid4()))
    payload = ErrorEnvelope(
        error=ErrorPayload(
            code=code,
            message=message,
            category=category,
            correlation_id=correlation_id,
            details=details,
        )
    )
    response = JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers=headers,
    )
    await response(scope, receive, send)
