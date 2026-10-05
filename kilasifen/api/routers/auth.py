"""Credential check route."""

from fastapi import APIRouter, Depends, Request

from kilasifen.api.deps import enforce_request_limits, get_api_key_principal
from kilasifen.api.errors import error_responses
from kilasifen.api.schemas.access import AuthCheckData, AuthCheckEnvelope

router = APIRouter(tags=["auth"])


@router.get(
    "/auth/check",
    response_model=AuthCheckEnvelope,
    responses=error_responses(401, 429, 503),
)
def auth_check(
    request: Request,
    _principal=Depends(get_api_key_principal),
    _limit=Depends(enforce_request_limits),
) -> AuthCheckEnvelope:
    return AuthCheckEnvelope(
        data=AuthCheckData(authenticated=True),
        correlation_id=request.state.correlation_id,
    )
