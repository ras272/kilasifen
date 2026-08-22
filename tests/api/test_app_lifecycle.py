from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.middleware import PreAuthRateLimitMiddleware


def test_app_closes_shared_limiter_redis_and_engine_once_on_shutdown() -> None:
    app = create_app()
    dispose = Mock(wraps=app.state.engine.dispose)
    close_redis = AsyncMock()
    app.state.engine.dispose = dispose
    app.state.request_limit_redis.aclose = close_redis
    middleware = next(
        item for item in app.user_middleware if item.cls is PreAuthRateLimitMiddleware
    )

    assert middleware.kwargs["redis"] is app.state.request_limit_redis

    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200

    dispose.assert_called_once_with()
    close_redis.assert_awaited_once_with()
