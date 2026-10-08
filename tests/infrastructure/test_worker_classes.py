"""Custom RQ workers: portable timeouts, and the job code loaded before forking."""

from __future__ import annotations

import sys

import fakeredis
import pytest
from rq.timeouts import TimerDeathPenalty

from kilasifen.engine.sdk import validation
from kilasifen.infrastructure.jobs import worker_classes
from kilasifen.infrastructure.jobs.worker_classes import (
    CrossPlatformSimpleWorker,
    PreloadedWorker,
    preload_job_runtime,
)


def test_cross_platform_simple_worker_uses_timer_death_penalty() -> None:
    assert CrossPlatformSimpleWorker.death_penalty_class is TimerDeathPenalty


def test_creating_the_worker_preloads_the_job_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        worker_classes, "preload_job_runtime", lambda: calls.append("preload")
    )

    worker = PreloadedWorker(["documents"], connection=fakeredis.FakeRedis())

    assert calls == ["preload"]
    assert [queue.name for queue in worker.queues] == ["documents"]


def test_preloading_imports_the_jobs_and_compiles_their_schemas() -> None:
    validation._load_schema.cache_clear()

    preload_job_runtime()

    assert "kilasifen.infrastructure.jobs.workers" in sys.modules
    assert validation._load_schema.cache_info().currsize == 2
