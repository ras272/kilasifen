from unittest.mock import AsyncMock

import pytest

from kilasifen.infrastructure.limits.redis import RedisRequestLimiter


@pytest.mark.anyio
async def test_request_limiter_acquires_and_releases_atomic_lease() -> None:
    redis = AsyncMock()
    redis.eval.side_effect = ([1, 1, 59, 2], 0)
    limiter = _limiter(redis)

    lease = await limiter.acquire("consumer:key:emitter")
    await limiter.release(lease)

    assert lease.acquired is True
    assert lease.reason is None
    assert redis.eval.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("result", "reason"),
    [([0, 121, 42, 0], "rate"), ([0, 8, 1, 1], "concurrency")],
)
async def test_request_limiter_reports_rejection_reason(
    result: list[int], reason: str
) -> None:
    redis = AsyncMock()
    redis.eval.return_value = result
    limiter = _limiter(redis)

    lease = await limiter.acquire("consumer:key:emitter")
    await limiter.release(lease)

    assert lease.acquired is False
    assert lease.reason == reason
    assert redis.eval.await_count == 1


def _limiter(redis: AsyncMock) -> RedisRequestLimiter:
    return RedisRequestLimiter(
        redis,
        requests_per_window=120,
        window_seconds=60,
        max_concurrent=8,
        lease_seconds=120,
    )
