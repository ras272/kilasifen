"""Health endpoint contracts."""

from typing import Literal

from pydantic import BaseModel


class DependencyCheckResponse(BaseModel):
    """Safe dependency state exposed by readiness."""

    status: Literal["ok", "down", "not_required"]
    detail: str | None = None


class ReadinessData(BaseModel):
    """Readiness payload with explicit dependency checks."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyCheckResponse]
