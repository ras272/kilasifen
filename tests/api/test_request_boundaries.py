from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from kilasifen.api.app import create_app
from kilasifen.api.deps import enforce_request_limits
from kilasifen.api.middleware import (
    NetworkIdentityResolver,
    PreAuthRateLimitMiddleware,
    RequestBodyLimitMiddleware,
    request_body_limit,
)
from kilasifen.config import Settings
from kilasifen.security import ApiKeyPrincipal


def test_untrusted_peer_cannot_rotate_forwarded_for_identity() -> None:
    resolver = NetworkIdentityResolver(["10.0.0.0/8"])
    first = _scope(
        client=("203.0.113.8", 1234),
        headers=[(b"x-forwarded-for", b"198.51.100.1")],
    )
    second = _scope(
        client=("203.0.113.8", 1234),
        headers=[(b"x-forwarded-for", b"198.51.100.200")],
    )

    assert resolver.resolve(first) == "203.0.113.8"
    assert resolver.resolve(second) == "203.0.113.8"


def test_trusted_proxy_chain_resolves_first_untrusted_hop() -> None:
    resolver = NetworkIdentityResolver(["10.0.0.0/8", "192.0.2.0/24"])
    scope = _scope(
        client=("10.0.0.9", 1234),
        headers=[
            (b"x-forwarded-for", b"203.0.113.44, 192.0.2.10"),
        ],
    )

    assert resolver.resolve(scope) == "203.0.113.44"


@pytest.mark.anyio
async def test_pre_auth_rejection_happens_before_downstream_auth(
    monkeypatch,
) -> None:
    redis = AsyncMock()
    redis.eval.return_value = [0, 601, 42, 0]
    monkeypatch.setattr(
        "kilasifen.api.middleware.AsyncRedis.from_url",
        lambda *args, **kwargs: redis,
    )
    downstream_called = False

    async def downstream(scope, receive, send) -> None:
        del scope, receive, send
        nonlocal downstream_called
        downstream_called = True

    middleware = PreAuthRateLimitMiddleware(
        downstream,
        settings=Settings.model_construct(
            environment="production",
            request_limits_enabled=True,
            redis_url="redis://limits.internal:6379/0",
            pre_auth_rate_limit_requests=600,
            rate_limit_window_seconds=60,
            pre_auth_max_concurrent_requests=32,
            request_lease_seconds=120,
            trusted_proxy_cidrs=[],
            api_version="v1",
        ),
    )
    sent = await _call_asgi(
        middleware,
        _scope(headers=[(b"x-forwarded-for", b"198.51.100.77")]),
        [b""],
    )

    assert downstream_called is False
    assert sent[0]["status"] == 429
    assert dict(sent[0]["headers"])[b"retry-after"] == b"42"


@pytest.mark.anyio
async def test_body_limit_rejects_oversized_content_length_before_downstream() -> None:
    called = False

    async def downstream(scope, receive, send) -> None:
        del scope, receive, send
        nonlocal called
        called = True

    middleware = RequestBodyLimitMiddleware(
        downstream,
        settings=Settings(max_json_request_body_bytes=1024, _env_file=None),
    )
    sent = await _call_asgi(
        middleware,
        _scope(headers=[(b"content-length", b"1025")]),
        [b"{}"],
    )

    assert called is False
    assert sent[0]["status"] == 413


@pytest.mark.anyio
async def test_body_limit_rejects_chunked_body_without_content_length() -> None:
    async def downstream(scope, receive, send) -> None:
        del scope
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestBodyLimitMiddleware(
        downstream,
        settings=Settings(max_json_request_body_bytes=1024, _env_file=None),
    )
    sent = await _call_asgi(middleware, _scope(), [b"x" * 700, b"y" * 400])

    assert sent[0]["status"] == 413


@pytest.mark.anyio
async def test_body_limit_preserves_legitimate_body_at_exact_limit() -> None:
    received = bytearray()

    async def downstream(scope, receive, send) -> None:
        del scope
        while True:
            message = await receive()
            received.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestBodyLimitMiddleware(
        downstream,
        settings=Settings(max_json_request_body_bytes=1024, _env_file=None),
    )
    sent = await _call_asgi(middleware, _scope(), [b"x" * 1024])

    assert sent[0]["status"] == 204
    assert len(received) == 1024


def test_certificate_upload_has_a_narrow_multipart_envelope() -> None:
    settings = Settings(
        max_json_request_body_bytes=1024,
        max_pfx_upload_bytes=4096,
        multipart_body_overhead_bytes=4096,
        _env_file=None,
    )
    certificate_scope = _scope(
        method="POST",
        path="/v1/emitters/emitter-1/certificates",
    )

    assert request_body_limit(certificate_scope, settings) == 8192
    assert request_body_limit(_scope(path="/v1/documents"), settings) == 1024


def test_oversized_json_is_rejected_before_authentication() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/emitters",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request.body_too_large"


@pytest.mark.anyio
async def test_post_auth_budget_cannot_be_bypassed_with_emitter_path(
    monkeypatch,
) -> None:
    redis = AsyncMock()
    redis.eval.side_effect = (
        [1, 1, 59, 2],
        0,
        [1, 2, 58, 2],
        0,
    )
    settings = Settings.model_construct(
        environment="production",
        redis_url="redis://limits.internal:6379/0",
        rate_limit_requests=120,
        rate_limit_window_seconds=60,
        max_concurrent_requests=8,
        request_lease_seconds=120,
    )
    monkeypatch.setattr("kilasifen.api.deps.get_settings", lambda: settings)
    monkeypatch.setattr(
        "kilasifen.api.deps.AsyncRedis.from_url",
        lambda *args, **kwargs: redis,
    )
    principal = ApiKeyPrincipal(
        key_id="key-1",
        consumer_id="consumer-1",
        scopes=frozenset(),
        emitter_ids=frozenset(),
    )

    await _acquire_post_auth_limit(redis, principal, "owned-emitter")
    await _acquire_post_auth_limit(redis, principal, "random-unowned-emitter")

    first_rate_key = redis.eval.await_args_list[0].args[2]
    second_rate_key = redis.eval.await_args_list[2].args[2]
    assert first_rate_key == second_rate_key


async def _acquire_post_auth_limit(
    redis: AsyncMock,
    principal: ApiKeyPrincipal,
    emitter_id: str,
) -> None:
    del redis
    dependency = enforce_request_limits(
        Request(_scope(path=f"/v1/emitters/{emitter_id}")),
        principal,
    )
    await anext(dependency)
    await dependency.aclose()


def _scope(
    *,
    method: str = "POST",
    path: str = "/v1/documents",
    client: tuple[str, int] = ("203.0.113.8", 1234),
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "client": client,
        "server": ("testserver", 443),
        "state": {},
    }


async def _call_asgi(app, scope: dict, chunks: list[bytes]) -> list[dict]:
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def receive() -> dict:
        return messages.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent
