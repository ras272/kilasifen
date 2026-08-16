from datetime import UTC, datetime, timedelta

import pytest

from kilasifen.infrastructure.webhooks.deliverer import (
    WebhookDeliverer,
    sanitize_response_snapshot,
)
from kilasifen.infrastructure.webhooks.security import (
    UnsafeWebhookUrlError,
    WebhookUrlPolicy,
    build_signature,
    verify_signature,
)

PUBLIC_IPV4 = "93.184.216.34"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "192.0.2.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
    ],
)
def test_url_policy_blocks_non_public_ipv4_and_ipv6(address: str) -> None:
    policy = WebhookUrlPolicy(resolver=lambda _host, _port: [address])

    with pytest.raises(UnsafeWebhookUrlError, match="webhooks.non_public_address"):
        policy.resolve("https://hooks.example.test/events")


def test_url_policy_requires_https_by_default() -> None:
    policy = WebhookUrlPolicy(resolver=lambda _host, _port: [PUBLIC_IPV4])

    with pytest.raises(UnsafeWebhookUrlError, match="webhooks.https_required"):
        policy.resolve("http://hooks.example.test/events")

    development_policy = WebhookUrlPolicy(
        allow_http=True,
        resolver=lambda _host, _port: [PUBLIC_IPV4],
    )
    assert (
        development_policy.resolve("http://hooks.example.test/events").scheme == "http"
    )


def test_url_policy_rejects_hostname_when_any_dns_answer_is_private() -> None:
    policy = WebhookUrlPolicy(resolver=lambda _host, _port: [PUBLIC_IPV4, "10.0.0.8"])

    with pytest.raises(UnsafeWebhookUrlError, match="webhooks.non_public_address"):
        policy.resolve("https://hooks.example.test/events")


def test_deliverer_revalidates_dns_and_does_not_follow_redirects() -> None:
    resolutions = []

    def resolver(host: str, port: int):
        resolutions.append((host, port))
        return [PUBLIC_IPV6]

    def sender(*, url: str, body: str, headers: dict[str, str], timeout: float):
        del url, body, headers, timeout
        return 302, "Location: http://127.0.0.1/admin"

    deliverer = WebhookDeliverer(
        sender=sender,
        url_policy=WebhookUrlPolicy(resolver=resolver),
    )
    outcome = deliverer.deliver(
        url="https://hooks.example.test/events",
        secret="secret",
        event_type="document.approved",
        delivery_id="delivery-1",
        payload_snapshot={"ok": True},
    )

    assert resolutions == [("hooks.example.test", 443)]
    assert outcome.final_status == "failed"
    assert outcome.retryable is False


def test_default_transport_receives_only_the_validated_pinned_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_send_pinned(*, target, body, headers, timeout, response_body_limit):
        del body, headers, timeout, response_body_limit
        captured["target"] = target
        return 204, ""

    monkeypatch.setattr(
        "kilasifen.infrastructure.webhooks.deliverer._send_pinned",
        fake_send_pinned,
    )
    deliverer = WebhookDeliverer(
        url_policy=WebhookUrlPolicy(
            resolver=lambda _host, _port: [PUBLIC_IPV4, PUBLIC_IPV6]
        )
    )
    outcome = deliverer.deliver(
        url="https://hooks.example.test/events",
        secret="secret",
        event_type="test.ping",
        delivery_id="delivery-1",
        payload_snapshot={},
    )

    assert outcome.final_status == "delivered"
    assert captured["target"].ip_addresses == (PUBLIC_IPV4, PUBLIC_IPV6)


def test_versioned_signature_covers_metadata_and_exact_body() -> None:
    now = datetime(2026, 8, 16, 20, 0, tzinfo=UTC)
    timestamp = str(int(now.timestamp()))
    body = b'{"value":1, "spacing":"is exact"}'
    signature = build_signature(
        secret="top-secret",
        timestamp=timestamp,
        delivery_id="delivery-1",
        event_type="document.approved",
        body=body,
    )

    verified = verify_signature(
        secret="top-secret",
        timestamp=timestamp,
        delivery_id="delivery-1",
        event_type="document.approved",
        body=body,
        signature=signature,
        now=now,
        is_delivery_processed=lambda _delivery_id: False,
    )
    changed_body = verify_signature(
        secret="top-secret",
        timestamp=timestamp,
        delivery_id="delivery-1",
        event_type="document.approved",
        body=body + b" ",
        signature=signature,
        now=now,
    )

    assert signature.startswith("v1=")
    assert verified.valid is True
    assert changed_body.reason == "invalid_signature"


def test_signature_verification_enforces_freshness_and_replay_lookup() -> None:
    now = datetime(2026, 8, 16, 20, 0, tzinfo=UTC)
    old_timestamp = str(int((now - timedelta(minutes=6)).timestamp()))
    body = b"{}"
    signature = build_signature(
        secret="secret",
        timestamp=old_timestamp,
        delivery_id="delivery-1",
        event_type="test.ping",
        body=body,
    )
    assert (
        verify_signature(
            secret="secret",
            timestamp=old_timestamp,
            delivery_id="delivery-1",
            event_type="test.ping",
            body=body,
            signature=signature,
            now=now,
        ).reason
        == "stale_timestamp"
    )

    fresh_timestamp = str(int(now.timestamp()))
    fresh_signature = build_signature(
        secret="secret",
        timestamp=fresh_timestamp,
        delivery_id="delivery-1",
        event_type="test.ping",
        body=body,
    )
    duplicate = verify_signature(
        secret="secret",
        timestamp=fresh_timestamp,
        delivery_id="delivery-1",
        event_type="test.ping",
        body=body,
        signature=fresh_signature,
        now=now,
        is_delivery_processed=lambda delivery_id: delivery_id == "delivery-1",
    )
    assert duplicate.reason == "duplicate_delivery"


def test_response_snapshot_is_bounded_and_redacts_credentials() -> None:
    snapshot = sanitize_response_snapshot(
        '{"password":"do-not-store","nested":{"api_key":"also-secret"},'
        f'"padding":"{"x" * 3000}"}}'
    )

    assert "do-not-store" not in snapshot
    assert "also-secret" not in snapshot
    assert "[REDACTED]" in snapshot
    assert snapshot.endswith("...[truncated]")
