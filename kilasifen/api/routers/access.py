"""Platform-admin API for consumer and credential lifecycle."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import get_access_service, get_admin_principal
from kilasifen.api.schemas.access import (
    ConsumerCreateRequest,
    ConsumerData,
    ConsumerEnvelope,
    ConsumerResponse,
    CredentialCreateRequest,
    CredentialData,
    CredentialEnvelope,
    CredentialResponse,
    IssuedCredentialData,
    IssuedCredentialEnvelope,
    IssuedCredentialResponse,
)
from kilasifen.application.access.service import AccessService

router = APIRouter(prefix="/admin/consumers", tags=["access administration"])


@router.post(
    "",
    response_model=ConsumerEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_consumer(
    payload: ConsumerCreateRequest,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AccessService = Depends(get_access_service),
) -> ConsumerEnvelope:
    consumer = service.create_consumer(name=payload.name)
    return ConsumerEnvelope(
        data=ConsumerData(consumer=ConsumerResponse.model_validate(consumer)),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/{consumer_id}/credentials",
    response_model=IssuedCredentialEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def issue_credential(
    consumer_id: str,
    payload: CredentialCreateRequest,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AccessService = Depends(get_access_service),
) -> IssuedCredentialEnvelope:
    credential, raw_key = service.issue_credential(
        consumer_id=consumer_id,
        name=payload.name,
        scopes=payload.scopes,
    )
    response = IssuedCredentialResponse.model_validate(
        {
            **CredentialResponse.model_validate(credential).model_dump(),
            "api_key": raw_key,
        }
    )
    return IssuedCredentialEnvelope(
        data=IssuedCredentialData(credential=response),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/{consumer_id}/credentials/{credential_id}/revoke",
    response_model=CredentialEnvelope,
)
def revoke_credential(
    consumer_id: str,
    credential_id: str,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AccessService = Depends(get_access_service),
) -> CredentialEnvelope:
    credential = service.revoke_credential(
        consumer_id=consumer_id,
        credential_id=credential_id,
    )
    return CredentialEnvelope(
        data=CredentialData(credential=CredentialResponse.model_validate(credential)),
        correlation_id=request.state.correlation_id,
    )
