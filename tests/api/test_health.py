import logging

from fastapi.testclient import TestClient

from kilasifen.api.app import create_app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok"}
    assert isinstance(body["correlation_id"], str)


def test_ready_endpoint_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ready"}
    assert isinstance(body["correlation_id"], str)


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
