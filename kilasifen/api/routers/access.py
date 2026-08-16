"""Platform-admin API for consumer and credential lifecycle."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import get_access_service, get_admin_principal
from kilasifen.api.schemas.access import (
    ConsumerCreateRequest,
    ConsumerResponse,
    CredentialCreateRequest,
    CredentialResponse,
    IssuedCredentialResponse,
)
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.application.access.service import AccessService

router = APIRouter(prefix="/admin/consumers", tags=["access administration"])


@router.post("", response_model=SuccessEnvelope, status_code=status.HTTP_201_CREATED)
def create_consumer(
    payload: ConsumerCreateRequest,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AccessService = Depends(get_access_service),
) -> SuccessEnvelope:
    consumer = service.create_consumer(name=payload.name)
    return SuccessEnvelope(
        data={
            "consumer": ConsumerResponse.model_validate(consumer).model_dump(
                mode="json"
            )
        },
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/{consumer_id}/credentials",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def issue_credential(
    consumer_id: str,
    payload: CredentialCreateRequest,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AccessService = Depends(get_access_service),
) -> SuccessEnvelope:
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
    return SuccessEnvelope(
        data={"credential": response.model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/{consumer_id}/credentials/{credential_id}/revoke",
    response_model=SuccessEnvelope,
)
def revoke_credential(
    consumer_id: str,
    credential_id: str,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AccessService = Depends(get_access_service),
) -> SuccessEnvelope:
    credential = service.revoke_credential(
        consumer_id=consumer_id,
        credential_id=credential_id,
    )
    return SuccessEnvelope(
        data={
            "credential": CredentialResponse.model_validate(credential).model_dump(
                mode="json"
            )
        },
        correlation_id=request.state.correlation_id,
    )
