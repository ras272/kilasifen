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
