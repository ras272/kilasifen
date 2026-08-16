"""Strict administrative access-control contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
