"""Security primitives for outbound webhook URLs and signatures."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

SIGNATURE_VERSION = "v1"
DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300


class UnsafeWebhookUrlError(ValueError):
    """Raised when a webhook target violates the outbound network policy."""


@dataclass(frozen=True, slots=True)
class ResolvedWebhookTarget:
    """A parsed target with every DNS answer validated."""

    url: str
    scheme: str
    hostname: str
    port: int
    request_target: str
    ip_addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignatureVerification:
    """Result returned to webhook consumers by the verification helper."""

    valid: bool
    reason: str
    delivery_id: str | None = None


DnsResolver = Callable[[str, int], list[str] | tuple[str, ...]]
ReplayLookup = Callable[[str], bool]


class WebhookUrlPolicy:
    """Validate schemes and DNS answers before every outbound connection."""

    def __init__(
        self,
        *,
        allow_http: bool = False,
        resolver: DnsResolver | None = None,
    ) -> None:
        self.allow_http = allow_http
        self.resolver = resolver or _resolve_all

    @classmethod
    def for_environment(
        cls,
        environment: str,
        *,
        resolver: DnsResolver | None = None,
    ) -> WebhookUrlPolicy:
        """Allow cleartext HTTP only for the explicit development runtime."""

        return cls(allow_http=environment == "development", resolver=resolver)

    def resolve(self, url: str) -> ResolvedWebhookTarget:
        parsed = urlsplit(url)
        allowed_schemes = {"https", "http"} if self.allow_http else {"https"}
        if parsed.scheme.lower() not in allowed_schemes:
            raise UnsafeWebhookUrlError("webhooks.https_required")
        if not parsed.hostname:
            raise UnsafeWebhookUrlError("webhooks.invalid_hostname")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeWebhookUrlError("webhooks.userinfo_forbidden")
        if parsed.fragment:
            raise UnsafeWebhookUrlError("webhooks.fragment_forbidden")

        scheme = parsed.scheme.lower()
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise UnsafeWebhookUrlError("webhooks.invalid_port") from exc
        if not 1 <= port <= 65535:
            raise UnsafeWebhookUrlError("webhooks.invalid_port")

        try:
            hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise UnsafeWebhookUrlError("webhooks.invalid_hostname") from exc
        try:
            literal_ip = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                addresses = tuple(dict.fromkeys(self.resolver(hostname, port)))
            except (OSError, socket.gaierror) as exc:
                raise UnsafeWebhookUrlError("webhooks.dns_resolution_failed") from exc
            if not addresses:
                raise UnsafeWebhookUrlError("webhooks.dns_resolution_failed")
        else:
            addresses = (str(literal_ip),)

        normalized_addresses: list[str] = []
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise UnsafeWebhookUrlError("webhooks.invalid_dns_answer") from exc
            if not _is_public_address(parsed_address):
                raise UnsafeWebhookUrlError("webhooks.non_public_address")
            normalized_addresses.append(str(parsed_address))

        request_target = parsed.path or "/"
        if parsed.query:
            request_target = f"{request_target}?{parsed.query}"
        return ResolvedWebhookTarget(
            url=url,
            scheme=scheme,
            hostname=hostname,
            port=port,
            request_target=request_target,
            ip_addresses=tuple(normalized_addresses),
        )


def build_signature(
    *,
    secret: str,
    timestamp: str,
    delivery_id: str,
    event_type: str,
    body: bytes,
) -> str:
    """Return the versioned HMAC for the exact HTTP body bytes."""

    content = _signature_content(
        timestamp=timestamp,
        delivery_id=delivery_id,
        event_type=event_type,
        body=body,
    )
    digest = hmac.new(secret.encode("utf-8"), content, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def verify_signature(
    *,
    secret: str,
    timestamp: str,
    delivery_id: str,
    event_type: str,
    body: bytes,
    signature: str,
    now: datetime | None = None,
    tolerance_seconds: int = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    is_delivery_processed: ReplayLookup | None = None,
) -> SignatureVerification:
    """Verify authenticity, freshness and optional persistent replay state.

    Consumers must call this helper before parsing ``body`` and must record the
    delivery ID atomically with their business transaction after accepting it.
    """

    try:
        issued_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return SignatureVerification(False, "invalid_timestamp")
    reference = now or datetime.now(UTC)
    if abs((reference - issued_at).total_seconds()) > tolerance_seconds:
        return SignatureVerification(False, "stale_timestamp", delivery_id)

    expected = build_signature(
        secret=secret,
        timestamp=timestamp,
        delivery_id=delivery_id,
        event_type=event_type,
        body=body,
    )
    if not hmac.compare_digest(expected.encode("ascii"), signature.encode("ascii")):
        return SignatureVerification(False, "invalid_signature", delivery_id)
    if is_delivery_processed is not None and is_delivery_processed(delivery_id):
        return SignatureVerification(False, "duplicate_delivery", delivery_id)
    return SignatureVerification(True, "verified", delivery_id)


def _signature_content(
    *,
    timestamp: str,
    delivery_id: str,
    event_type: str,
    body: bytes,
) -> bytes:
    prefix = f"{SIGNATURE_VERSION}.{timestamp}.{delivery_id}.{event_type}.".encode(
        "utf-8"
    )
    return prefix + body


def _resolve_all(hostname: str, port: int) -> list[str]:
    answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return [answer[4][0] for answer in answers]


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # is_global excludes loopback, private, link-local, multicast, reserved,
    # unspecified and IPv4-mapped internal IPv6 ranges on supported Python versions.
    if (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_global
    return True
