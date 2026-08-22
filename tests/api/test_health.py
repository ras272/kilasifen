import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_readiness_service
from kilasifen.application.health.service import DependencyCheck, ReadinessReport


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok"}
    assert isinstance(body["correlation_id"], str)


def test_ready_endpoint_returns_ok() -> None:
    app = create_app()
    app.dependency_overrides[get_readiness_service] = lambda: _ReadinessStub(
        ReadinessReport(
            database=DependencyCheck("ok"),
            redis=DependencyCheck("ok"),
            workers=DependencyCheck("not_required"),
        )
    )
    client = TestClient(app)

    response = client.get("/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {
        "status": "ready",
        "checks": {
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
            "workers": {"status": "not_required"},
        },
    }
    assert isinstance(body["correlation_id"], str)


def test_ready_endpoint_returns_503_when_a_dependency_is_down() -> None:
    app = create_app()
    app.dependency_overrides[get_readiness_service] = lambda: _ReadinessStub(
        ReadinessReport(
            database=DependencyCheck("ok"),
            redis=DependencyCheck("down"),
            workers=DependencyCheck("down"),
        )
    )
    client = TestClient(app)

    response = client.get("/v1/ready")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "not_ready"
    assert response.json()["data"]["checks"]["redis"] == {"status": "down"}


def test_ready_endpoint_reuses_a_recent_dependency_probe() -> None:
    app = create_app()
    stub = _ReadinessStub(
        ReadinessReport(
            database=DependencyCheck("ok"),
            redis=DependencyCheck("ok"),
            workers=DependencyCheck("not_required"),
        )
    )
    app.dependency_overrides[get_readiness_service] = lambda: stub
    client = TestClient(app)

    assert client.get("/v1/ready").status_code == 200
    assert client.get("/v1/ready").status_code == 200

    assert stub.check_count == 1


def test_ready_waiter_and_health_do_not_block_behind_probe_refresh() -> None:
    app = create_app()
    stub = _BlockingReadinessStub()
    app.dependency_overrides[get_readiness_service] = lambda: stub

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        first_ready = executor.submit(client.get, "/v1/ready")
        assert stub.started.wait(timeout=2)
        try:
            concurrent_ready = client.get("/v1/ready")
            health = client.get("/v1/health")
        finally:
            stub.release.set()

        assert concurrent_ready.status_code == 503
        assert concurrent_ready.json()["data"]["status"] == "not_ready"
        assert health.status_code == 200
        assert first_ready.result(timeout=2).status_code == 200
        assert stub.check_count == 1


def test_health_request_emits_structured_request_log(
    caplog,
) -> None:
    client = TestClient(create_app())
    caplog.set_level(logging.INFO)

    response = client.get("/v1/health")

    assert response.status_code == 200
    request_logs = [
        record
        for record in caplog.records
        if record.getMessage() == "http.request.completed"
    ]
    assert request_logs
    record = request_logs[-1]
    assert record.method == "GET"
    assert record.path == "/v1/health"
    assert record.status_code == 200


class _ReadinessStub:
    def __init__(self, report: ReadinessReport):
        self.report = report
        self.check_count = 0

    def check(self) -> ReadinessReport:
        self.check_count += 1
        return self.report


class _BlockingReadinessStub(_ReadinessStub):
    def __init__(self) -> None:
        super().__init__(
            ReadinessReport(
                database=DependencyCheck("ok"),
                redis=DependencyCheck("ok"),
                workers=DependencyCheck("not_required"),
            )
        )
        self.started = Event()
        self.release = Event()

    def check(self) -> ReadinessReport:
        self.check_count += 1
        self.started.set()
        assert self.release.wait(timeout=2)
        return self.report
