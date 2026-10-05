"""Webhook API routes."""

from fastapi import APIRouter, Depends, Query, Request, status

from kilasifen.api.deps import (
    get_admin_principal,
    get_webhook_service,
    require_emitter_read,
    require_emitter_write,
)
from kilasifen.api.schemas.common import Pagination
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.api.schemas.webhooks import (
    CreatedWebhookDeliveryData,
    CreatedWebhookDeliveryEnvelope,
    WebhookDeliveryListData,
    WebhookDeliveryListEnvelope,
    WebhookDeliveryResponse,
    WebhookDeliveryWithJobData,
    WebhookDeliveryWithJobEnvelope,
    WebhookEndpointCreateRequest,
    WebhookEndpointData,
    WebhookEndpointEnvelope,
    WebhookEndpointListData,
    WebhookEndpointListEnvelope,
    WebhookEndpointResponse,
    WebhookEndpointUpdateRequest,
    WebhookReplayRequest,
)
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint

router = APIRouter(tags=["webhooks"])


@router.post(
    "/emitters/{emitter_id}/webhooks",
    response_model=WebhookEndpointEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def register_webhook_endpoint(
    emitter_id: str,
    payload: WebhookEndpointCreateRequest,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookEndpointEnvelope:
    endpoint = service.register_endpoint(
        emitter_id=emitter_id,
        url=str(payload.url),
        secret=payload.secret,
        event_subscriptions=payload.event_subscriptions,
        retry_policy=(
            payload.retry_policy.model_dump() if payload.retry_policy else None
        ),
    )
    return WebhookEndpointEnvelope(
        data=WebhookEndpointData(webhook_endpoint=_endpoint_response(endpoint)),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/emitters/{emitter_id}/webhooks",
    response_model=WebhookEndpointListEnvelope,
)
def list_webhook_endpoints(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookEndpointListEnvelope:
    endpoints = service.list_endpoints(emitter_id)
    return WebhookEndpointListEnvelope(
        data=WebhookEndpointListData(
            webhook_endpoints=[_endpoint_response(endpoint) for endpoint in endpoints]
        ),
        correlation_id=request.state.correlation_id,
    )


@router.patch(
    "/emitters/{emitter_id}/webhooks/{endpoint_id}",
    response_model=WebhookEndpointEnvelope,
)
def update_webhook_endpoint(
    emitter_id: str,
    endpoint_id: str,
    payload: WebhookEndpointUpdateRequest,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookEndpointEnvelope:
    changes = payload.model_dump(exclude_unset=True, mode="json")
    endpoint = service.update_endpoint(
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
        changes=changes,
    )
    return WebhookEndpointEnvelope(
        data=WebhookEndpointData(webhook_endpoint=_endpoint_response(endpoint)),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/webhooks/{endpoint_id}/deliveries/replay",
    response_model=CreatedWebhookDeliveryEnvelope,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Reenvía a este endpoint un evento que KilaSifen ya generó para el "
        "emisor, identificado por `delivery_id`. No acepta tipo de evento ni "
        "payload del caller, y el endpoint tiene que estar suscripto al tipo "
        "del evento (`409 webhooks.event_not_subscribed`)."
    ),
)
def replay_webhook_delivery(
    emitter_id: str,
    endpoint_id: str,
    payload: WebhookReplayRequest,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> CreatedWebhookDeliveryEnvelope:
    delivery, job = service.replay_delivery_for_emitter(
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
        delivery_id=payload.delivery_id,
    )
    return _delivery_envelope(request, delivery, job)


@router.post(
    "/emitters/{emitter_id}/webhooks/{endpoint_id}/test",
    response_model=CreatedWebhookDeliveryEnvelope,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Envía un evento sintético `webhook.test`, firmado como cualquier "
        "entrega, para verificar conectividad y firma. Su `data` es fija y "
        "nunca representa un cambio de estado fiscal."
    ),
)
def send_webhook_test_event(
    emitter_id: str,
    endpoint_id: str,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> CreatedWebhookDeliveryEnvelope:
    delivery, job = service.send_test_event_for_emitter(
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
    )
    return _delivery_envelope(request, delivery, job)


@router.get(
    "/emitters/{emitter_id}/webhook-deliveries/{delivery_id}",
    response_model=WebhookDeliveryWithJobEnvelope,
)
def get_webhook_delivery(
    emitter_id: str,
    delivery_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookDeliveryWithJobEnvelope:
    delivery, job = service.get_delivery_for_emitter(
        emitter_id=emitter_id,
        delivery_id=delivery_id,
    )
    return WebhookDeliveryWithJobEnvelope(
        data=WebhookDeliveryWithJobData(
            delivery=WebhookDeliveryResponse.model_validate(delivery),
            job=JobResponse.model_validate(job) if job else None,
        ),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/webhook-deliveries", response_model=WebhookDeliveryListEnvelope
)
def list_webhook_deliveries(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    emitter_id: str | None = None,
    endpoint_id: str | None = None,
    status: str | None = None,
    _principal=Depends(get_admin_principal),
    service: WebhookService = Depends(get_webhook_service),
) -> WebhookDeliveryListEnvelope:
    statuses = [status] if status else None
    deliveries = service.list_deliveries(
        limit=limit,
        offset=offset,
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
        statuses=statuses,
    )
    return WebhookDeliveryListEnvelope(
        data=WebhookDeliveryListData(
            deliveries=[
                WebhookDeliveryResponse.model_validate(delivery)
                for delivery in deliveries
            ],
            pagination=Pagination(limit=limit, offset=offset, count=len(deliveries)),
        ),
        correlation_id=request.state.correlation_id,
    )


def _delivery_envelope(
    request: Request,
    delivery: WebhookDelivery,
    job: Job,
) -> CreatedWebhookDeliveryEnvelope:
    return CreatedWebhookDeliveryEnvelope(
        data=CreatedWebhookDeliveryData(
            delivery=WebhookDeliveryResponse.model_validate(delivery),
            job=JobResponse.model_validate(job),
        ),
        correlation_id=request.state.correlation_id,
    )


def _endpoint_response(
    endpoint: WebhookEndpoint,
) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=endpoint.id,
        emitter_id=endpoint.emitter_id,
        url=endpoint.url,
        event_subscriptions=endpoint.event_subscriptions,
        is_active=endpoint.is_active,
        retry_policy=endpoint.retry_policy,
        secret_configured=True,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )
