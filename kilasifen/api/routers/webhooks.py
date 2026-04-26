"""Webhook API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import get_api_key_principal, get_webhook_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.api.schemas.webhooks import (
    WebhookDeliveryResponse,
    WebhookEndpointCreateRequest,
    WebhookEndpointResponse,
    WebhookReplayRequest,
)
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.domain.webhooks.models import WebhookEndpoint

router = APIRouter(tags=["webhooks"])


@router.post(
    "/emitters/{emitter_id}/webhooks",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def register_webhook_endpoint(
    emitter_id: str,
    payload: WebhookEndpointCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    endpoint = service.register_endpoint(
        emitter_id=emitter_id,
        url=str(payload.url),
        secret=payload.secret,
        event_subscriptions=payload.event_subscriptions,
        retry_policy=payload.retry_policy,
    )
    return SuccessEnvelope(
        data={
            "webhook_endpoint": _endpoint_response(
                endpoint,
                secret_preview=service.get_secret_preview(endpoint),
            ).model_dump(mode="json")
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/emitters/{emitter_id}/webhooks", response_model=SuccessEnvelope)
def list_webhook_endpoints(
    emitter_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    endpoints = service.list_endpoints(emitter_id)
    return SuccessEnvelope(
        data={
            "webhook_endpoints": [
                _endpoint_response(
                    endpoint,
                    secret_preview=service.get_secret_preview(endpoint),
                ).model_dump(mode="json")
                for endpoint in endpoints
            ]
        },
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/webhooks/{endpoint_id}/deliveries/replay",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def replay_webhook_delivery(
    endpoint_id: str,
    payload: WebhookReplayRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    delivery, job = service.replay_delivery(
        endpoint_id=endpoint_id,
        event_type=payload.event_type,
        payload=payload.payload,
    )
    return SuccessEnvelope(
        data={
            "delivery": WebhookDeliveryResponse.model_validate(delivery).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/webhook-deliveries/{delivery_id}", response_model=SuccessEnvelope)
def get_webhook_delivery(
    delivery_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    delivery, job = service.get_delivery(delivery_id)
    return SuccessEnvelope(
        data={
            "delivery": WebhookDeliveryResponse.model_validate(delivery).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json") if job else None,
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/webhook-deliveries", response_model=SuccessEnvelope)
def list_webhook_deliveries(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    # TODO(multi-tenant): require emitter scoping by principal when opening API to multiple tenants.
    emitter_id: str | None = None,
    endpoint_id: str | None = None,
    status: str | None = None,
    _principal=Depends(get_api_key_principal),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    statuses = [status] if status else None
    deliveries = service.list_deliveries(
        limit=limit,
        offset=offset,
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
        statuses=statuses,
    )
    return SuccessEnvelope(
        data={
            "deliveries": [
                WebhookDeliveryResponse.model_validate(delivery).model_dump(mode="json")
                for delivery in deliveries
            ],
            "pagination": {"limit": limit, "offset": offset, "count": len(deliveries)},
        },
        correlation_id=request.state.correlation_id,
    )


def _endpoint_response(
    endpoint: WebhookEndpoint,
    *,
    secret_preview: str,
) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=endpoint.id,
        emitter_id=endpoint.emitter_id,
        url=endpoint.url,
        event_subscriptions=endpoint.event_subscriptions,
        is_active=endpoint.is_active,
        retry_policy=endpoint.retry_policy,
        secret_preview=secret_preview,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )
