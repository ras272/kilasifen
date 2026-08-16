"""Atomic Redis request-rate and in-flight concurrency leases."""

import time
from dataclasses import dataclass
from hashlib import sha256

from redis.asyncio import Redis

_ACQUIRE_SCRIPT = """
local request_count = redis.call('INCR', KEYS[1])
if request_count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local retry_after = redis.call('TTL', KEYS[1])
if request_count > tonumber(ARGV[1]) then
  return {0, request_count, retry_after, 0}
end

local in_flight = redis.call('INCR', KEYS[2])
if in_flight == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[4])
end
if in_flight > tonumber(ARGV[3]) then
  redis.call('DECR', KEYS[2])
  return {0, request_count, 1, 1}
end
redis.call('EXPIRE', KEYS[2], ARGV[4])
return {1, request_count, retry_after, 2}
"""

_RELEASE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if not current then
  return 0
end
if tonumber(current) <= 1 then
  redis.call('DEL', KEYS[1])
  return 0
end
return redis.call('DECR', KEYS[1])
"""


@dataclass(frozen=True, slots=True)
class RequestLease:
    """One acquired in-flight slot and its rate-window state."""

    acquired: bool
    retry_after_seconds: int
    reason: str | None
    concurrency_key: str


class RedisRequestLimiter:
    """Enforce atomic limits shared by every API replica."""

    def __init__(
        self,
        redis: Redis,
        *,
        requests_per_window: int,
        window_seconds: int,
        max_concurrent: int,
        lease_seconds: int,
    ) -> None:
        self.redis = redis
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.max_concurrent = max_concurrent
        self.lease_seconds = lease_seconds

    async def acquire(self, identity: str) -> RequestLease:
        identity_hash = sha256(identity.encode("utf-8")).hexdigest()
        window = int(time.time()) // self.window_seconds
        rate_key = f"kilasifen:limit:rate:{identity_hash}:{window}"
        concurrency_key = f"kilasifen:limit:inflight:{identity_hash}"
        result = await self.redis.eval(
            _ACQUIRE_SCRIPT,
            2,
            rate_key,
            concurrency_key,
            self.requests_per_window,
            self.window_seconds,
            self.max_concurrent,
            self.lease_seconds,
        )
        acquired, _count, retry_after, reason_code = (int(value) for value in result)
        reason = {0: "rate", 1: "concurrency", 2: None}[reason_code]
        return RequestLease(
            acquired=bool(acquired),
            retry_after_seconds=max(1, retry_after),
            reason=reason,
            concurrency_key=concurrency_key,
        )

    async def release(self, lease: RequestLease) -> None:
        if lease.acquired:
            await self.redis.eval(_RELEASE_SCRIPT, 1, lease.concurrency_key)
