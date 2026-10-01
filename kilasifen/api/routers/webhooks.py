"""Webhook API routes."""

from fastapi import APIRouter, Depends, Query, Request, status

from kilasifen.api.deps import (
    get_admin_principal,
    get_webhook_service,
    require_emitter_read,
    require_emitter_write,
)
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.api.schemas.webhooks import (
    WebhookDeliveryResponse,
    WebhookEndpointCreateRequest,
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
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def register_webhook_endpoint(
    emitter_id: str,
    payload: WebhookEndpointCreateRequest,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    endpoint = service.register_endpoint(
        emitter_id=emitter_id,
        url=str(payload.url),
        secret=payload.secret,
        event_subscriptions=payload.event_subscriptions,
        retry_policy=(
            payload.retry_policy.model_dump() if payload.retry_policy else None
        ),
    )
    return SuccessEnvelope(
        data={
            "webhook_endpoint": _endpoint_response(
                endpoint,
            ).model_dump(mode="json")
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/emitters/{emitter_id}/webhooks", response_model=SuccessEnvelope)
def list_webhook_endpoints(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    endpoints = service.list_endpoints(emitter_id)
    return SuccessEnvelope(
        data={
            "webhook_endpoints": [
                _endpoint_response(
                    endpoint,
                ).model_dump(mode="json")
                for endpoint in endpoints
            ]
        },
        correlation_id=request.state.correlation_id,
    )


@router.patch(
    "/emitters/{emitter_id}/webhooks/{endpoint_id}",
    response_model=SuccessEnvelope,
)
def update_webhook_endpoint(
    emitter_id: str,
    endpoint_id: str,
    payload: WebhookEndpointUpdateRequest,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    changes = payload.model_dump(exclude_unset=True, mode="json")
    endpoint = service.update_endpoint(
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
        changes=changes,
    )
    return SuccessEnvelope(
        data={"webhook_endpoint": _endpoint_response(endpoint).model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/webhooks/{endpoint_id}/deliveries/replay",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Reenvía a este endpoint un evento que KilaSifen ya generó para el "
        "emisor, identificado por `delivery_id`. No acepta tipo de evento ni "
        "payload del caller."
    ),
)
def replay_webhook_delivery(
    emitter_id: str,
    endpoint_id: str,
    payload: WebhookReplayRequest,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    delivery, job = service.replay_delivery_for_emitter(
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
        delivery_id=payload.delivery_id,
    )
    return _delivery_envelope(request, delivery, job)


@router.post(
    "/emitters/{emitter_id}/webhooks/{endpoint_id}/test",
    response_model=SuccessEnvelope,
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
) -> SuccessEnvelope:
    delivery, job = service.send_test_event_for_emitter(
        emitter_id=emitter_id,
        endpoint_id=endpoint_id,
    )
    return _delivery_envelope(request, delivery, job)


@router.get(
    "/emitters/{emitter_id}/webhook-deliveries/{delivery_id}",
    response_model=SuccessEnvelope,
)
def get_webhook_delivery(
    emitter_id: str,
    delivery_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: WebhookService = Depends(get_webhook_service),
) -> SuccessEnvelope:
    delivery, job = service.get_delivery_for_emitter(
        emitter_id=emitter_id,
        delivery_id=delivery_id,
    )
    return SuccessEnvelope(
        data={
            "delivery": WebhookDeliveryResponse.model_validate(delivery).model_dump(
                mode="json"
            ),
            "job": JobResponse.model_validate(job).model_dump(mode="json")
            if job
            else None,
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/webhook-deliveries", response_model=SuccessEnvelope)
def list_webhook_deliveries(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    emitter_id: str | None = None,
    endpoint_id: str | None = None,
    status: str | None = None,
    _principal=Depends(get_admin_principal),
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


def _delivery_envelope(
    request: Request,
    delivery: WebhookDelivery,
    job: Job,
) -> SuccessEnvelope:
    return SuccessEnvelope(
        data={
            "delivery": WebhookDeliveryResponse.model_validate(delivery).model_dump(
                mode="json"
            ),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
        },
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
