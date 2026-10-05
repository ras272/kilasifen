"""Health endpoint contracts."""

from typing import Literal

from pydantic import BaseModel

from kilasifen.api.schemas.common import SuccessEnvelope


class DependencyCheckResponse(BaseModel):
    """Estado de una dependencia, sin datos sensibles."""

    status: Literal["ok", "down", "not_required"]
    detail: str | None = None


class ReadinessData(BaseModel):
    """Readiness con el estado de cada dependencia obligatoria."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyCheckResponse]


class HealthData(BaseModel):
    """Liveness del proceso de la API."""

    status: Literal["ok"]


class HealthEnvelope(SuccessEnvelope[HealthData]):
    """Respuesta de liveness."""


class ReadinessEnvelope(SuccessEnvelope[ReadinessData]):
    """Respuesta de readiness."""
