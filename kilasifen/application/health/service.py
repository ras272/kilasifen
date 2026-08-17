"""Readiness checks for mandatory platform dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from redis import Redis
from rq import Worker
from sqlalchemy import text
from sqlalchemy.engine import Engine

CheckStatus = Literal["ok", "down", "not_required"]


@dataclass(frozen=True, slots=True)
class DependencyCheck:
    """Public, non-sensitive state for one runtime dependency."""

    status: CheckStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Aggregate readiness state returned by the application layer."""

    database: DependencyCheck
    redis: DependencyCheck
    workers: DependencyCheck

    @property
    def is_ready(self) -> bool:
        return all(
            check.status in {"ok", "not_required"}
            for check in (self.database, self.redis, self.workers)
        )


class ReadinessService:
    """Probe PostgreSQL, Redis, and the required RQ queues."""

    def __init__(
        self,
        *,
        engine: Engine,
        redis_connection: Redis,
        require_workers: bool,
        required_queues: tuple[str, ...] = ("documents", "events", "webhooks"),
    ) -> None:
        self._engine = engine
        self._redis = redis_connection
        self._require_workers = require_workers
        self._required_queues = required_queues

    def check(self) -> ReadinessReport:
        """Return a safe readiness report without leaking connection details."""

        database = self._check_database()
        redis = self._check_redis()
        workers = (
            self._check_workers() if redis.status == "ok" else DependencyCheck("down")
        )
        return ReadinessReport(database=database, redis=redis, workers=workers)

    def _check_database(self) -> DependencyCheck:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return DependencyCheck("down")
        return DependencyCheck("ok")

    def _check_redis(self) -> DependencyCheck:
        try:
            if not self._redis.ping():
                return DependencyCheck("down")
        except Exception:
            return DependencyCheck("down")
        return DependencyCheck("ok")

    def _check_workers(self) -> DependencyCheck:
        if not self._require_workers:
            return DependencyCheck("not_required")

        try:
            registered_queues = {
                queue_name
                for worker in Worker.all(connection=self._redis)
                for queue_name in worker.queue_names()
            }
        except Exception:
            return DependencyCheck("down")

        missing = sorted(set(self._required_queues) - registered_queues)
        if missing:
            return DependencyCheck("down", detail="missing:" + ",".join(missing))
        return DependencyCheck("ok")
