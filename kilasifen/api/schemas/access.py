"""Strict administrative access-control contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kilasifen.api.schemas.common import SuccessEnvelope


class ConsumerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)


class CredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=4)


class ConsumerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    consumer_id: str
    name: str
    key_prefix: str
    scopes: tuple[str, ...]
    status: str
    created_at: datetime
    updated_at: datetime


class IssuedCredentialResponse(CredentialResponse):
    api_key: str = Field(repr=False)


class ConsumerData(BaseModel):
    """Consumidor de la API."""

    consumer: ConsumerResponse


class CredentialData(BaseModel):
    """Credencial, sin la API key."""

    credential: CredentialResponse


class IssuedCredentialData(BaseModel):
    """Credencial recién emitida: `api_key` se muestra sólo esta vez."""

    credential: IssuedCredentialResponse


class AuthCheckData(BaseModel):
    """Resultado de la comprobación de la API key."""

    authenticated: Literal[True]


class ConsumerEnvelope(SuccessEnvelope[ConsumerData]):
    """Respuesta con un consumidor."""


class CredentialEnvelope(SuccessEnvelope[CredentialData]):
    """Respuesta con una credencial."""


class IssuedCredentialEnvelope(SuccessEnvelope[IssuedCredentialData]):
    """Respuesta con la credencial recién emitida."""


class AuthCheckEnvelope(SuccessEnvelope[AuthCheckData]):
    """Respuesta de la comprobación de la API key."""
