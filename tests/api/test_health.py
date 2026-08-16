import logging

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

    def check(self) -> ReadinessReport:
        return self.report
