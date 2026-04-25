"""Shared API dependencies."""

from collections.abc import Callable, Generator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from kilasifen.application.emitters.service import EmitterService
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.session import session_scope
from kilasifen.security import ApiKeyPrincipal, validate_api_key


def get_api_key_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyPrincipal:
    """Resolve and validate the caller API key."""

    return validate_api_key(x_api_key)


RequireApiKey = Callable[..., ApiKeyPrincipal]


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Provide a database session for request handlers."""

    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        yield session


def get_emitter_service(session: Session = Depends(get_db_session)) -> EmitterService:
    """Build the emitter application service for one request."""

    repository = SqlAlchemyEmitterRepository(session)
    return EmitterService(repository)
