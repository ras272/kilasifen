from unittest.mock import Mock

from fastapi.testclient import TestClient

from kilasifen.api.app import create_app


def test_app_disposes_database_engine_on_shutdown() -> None:
    app = create_app()
    dispose = Mock(wraps=app.state.engine.dispose)
    app.state.engine.dispose = dispose

    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200

    dispose.assert_called_once_with()
