from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock, patch

from sqlalchemy import create_engine

from kilasifen.application.health.service import (
    DependencyCheck,
    ReadinessProbeCache,
    ReadinessReport,
    ReadinessService,
)


def test_readiness_cache_coalesces_concurrent_dependency_probes() -> None:
    cache = ReadinessProbeCache(ttl_seconds=30)
    started = Event()
    release = Event()
    call_count = 0
    report = ReadinessReport(
        database=DependencyCheck("ok"),
        redis=DependencyCheck("ok"),
        workers=DependencyCheck("not_required"),
    )

    def check() -> ReadinessReport:
        nonlocal call_count
        call_count += 1
        started.set()
        assert release.wait(timeout=2)
        return report

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get_or_check, check)
        assert started.wait(timeout=2)
        second = executor.submit(cache.get_or_check, check)
        release.set()

        assert first.result(timeout=2) is report
        assert second.result(timeout=2) is report

    assert call_count == 1


def test_readiness_reports_healthy_dependencies_when_workers_are_optional() -> None:
    redis_connection = Mock()
    redis_connection.ping.return_value = True
    service = ReadinessService(
        engine=create_engine("sqlite:///:memory:"),
        redis_connection=redis_connection,
        require_workers=False,
    )

    report = service.check()

    assert report.is_ready is True
    assert report.database.status == "ok"
    assert report.redis.status == "ok"
    assert report.workers.status == "not_required"


def test_readiness_fails_when_database_is_down() -> None:
    engine = Mock()
    engine.connect.side_effect = OSError("database unavailable")
    redis_connection = Mock()
    redis_connection.ping.return_value = True
    service = ReadinessService(
        engine=engine,
        redis_connection=redis_connection,
        require_workers=False,
    )

    report = service.check()

    assert report.is_ready is False
    assert report.database.status == "down"


def test_readiness_fails_when_redis_is_down() -> None:
    redis_connection = Mock()
    redis_connection.ping.side_effect = OSError("redis unavailable")
    service = ReadinessService(
        engine=create_engine("sqlite:///:memory:"),
        redis_connection=redis_connection,
        require_workers=True,
    )

    report = service.check()

    assert report.is_ready is False
    assert report.redis.status == "down"
    assert report.workers.status == "down"


def test_readiness_requires_workers_for_every_required_queue() -> None:
    redis_connection = Mock()
    redis_connection.ping.return_value = True
    document_worker = Mock()
    document_worker.queue_names.return_value = ["documents"]
    service = ReadinessService(
        engine=create_engine("sqlite:///:memory:"),
        redis_connection=redis_connection,
        require_workers=True,
    )

    with patch(
        "kilasifen.application.health.service.Worker.all",
        return_value=[document_worker],
    ):
        report = service.check()

    assert report.is_ready is False
    assert report.workers.status == "down"
    assert report.workers.detail == "missing:events,webhooks"


def test_readiness_accepts_workers_covering_all_required_queues() -> None:
    redis_connection = Mock()
    redis_connection.ping.return_value = True
    redis_connection.exists.return_value = True
    worker = Mock()
    worker.queue_names.return_value = ["documents", "events", "webhooks"]
    service = ReadinessService(
        engine=create_engine("sqlite:///:memory:"),
        redis_connection=redis_connection,
        require_workers=True,
    )

    with patch(
        "kilasifen.application.health.service.Worker.all",
        return_value=[worker],
    ):
        report = service.check()

    assert report.is_ready is True
    assert report.workers.status == "ok"


def test_readiness_requires_outbox_dispatcher_heartbeat() -> None:
    redis_connection = Mock()
    redis_connection.ping.return_value = True
    redis_connection.exists.return_value = False
    worker = Mock()
    worker.queue_names.return_value = ["documents", "events", "webhooks"]
    service = ReadinessService(
        engine=create_engine("sqlite:///:memory:"),
        redis_connection=redis_connection,
        require_workers=True,
    )

    with patch(
        "kilasifen.application.health.service.Worker.all",
        return_value=[worker],
    ):
        report = service.check()

    assert report.is_ready is False
    assert report.workers.detail == "missing:outbox_dispatcher"
