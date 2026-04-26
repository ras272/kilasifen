"""SQLAlchemy implementation of webhook repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint
from kilasifen.infrastructure.db.models import WebhookDeliveryModel, WebhookEndpointModel
from kilasifen.repositories.webhooks import WebhookRepository


class SqlAlchemyWebhookRepository(WebhookRepository):
    """Persist webhook endpoints and deliveries with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save_endpoint(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        existing = self.session.get(WebhookEndpointModel, endpoint.id)
        if existing is None:
            model = WebhookEndpointModel(
                id=endpoint.id,
                emitter_id=endpoint.emitter_id,
                url=endpoint.url,
                secret_encrypted=endpoint.secret_encrypted,
                event_subscriptions=endpoint.event_subscriptions,
                is_active=endpoint.is_active,
                retry_policy=endpoint.retry_policy,
                created_at=endpoint.created_at,
                updated_at=endpoint.updated_at,
            )
            self.session.add(model)
        else:
            existing.url = endpoint.url
            existing.secret_encrypted = endpoint.secret_encrypted
            existing.event_subscriptions = endpoint.event_subscriptions
            existing.is_active = endpoint.is_active
            existing.retry_policy = endpoint.retry_policy
            existing.updated_at = endpoint.updated_at
        self.session.flush()
        return endpoint

    def get_endpoint(self, endpoint_id: str) -> WebhookEndpoint | None:
        model = self.session.get(WebhookEndpointModel, endpoint_id)
        if model is None:
            return None
        return _endpoint_to_domain(model)

    def list_endpoints_for_emitter(self, emitter_id: str) -> list[WebhookEndpoint]:
        statement = (
            select(WebhookEndpointModel)
            .where(WebhookEndpointModel.emitter_id == emitter_id)
            .order_by(WebhookEndpointModel.created_at.desc())
        )
        return [_endpoint_to_domain(model) for model in self.session.scalars(statement)]

    def save_delivery(self, delivery: WebhookDelivery) -> WebhookDelivery:
        existing = self.session.get(WebhookDeliveryModel, delivery.id)
        if existing is None:
            model = WebhookDeliveryModel(
                id=delivery.id,
                webhook_endpoint_id=delivery.webhook_endpoint_id,
                event_type=delivery.event_type,
                payload_snapshot=delivery.payload_snapshot,
                attempt_number=delivery.attempt_number,
                request_at=delivery.request_at,
                response_code=delivery.response_code,
                response_body_snapshot=delivery.response_body_snapshot,
                final_status=delivery.final_status,
                created_at=delivery.created_at,
                updated_at=delivery.updated_at,
            )
            self.session.add(model)
        else:
            existing.event_type = delivery.event_type
            existing.payload_snapshot = delivery.payload_snapshot
            existing.attempt_number = delivery.attempt_number
            existing.request_at = delivery.request_at
            existing.response_code = delivery.response_code
            existing.response_body_snapshot = delivery.response_body_snapshot
            existing.final_status = delivery.final_status
            existing.updated_at = delivery.updated_at
        self.session.flush()
        return delivery

    def get_delivery(self, delivery_id: str) -> WebhookDelivery | None:
        model = self.session.get(WebhookDeliveryModel, delivery_id)
        if model is None:
            return None
        return _delivery_to_domain(model)

    def list_recent_deliveries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        endpoint_id: str | None = None,
        emitter_id: str | None = None,
        statuses: list[str] | None = None,
    ) -> list[WebhookDelivery]:
        statement = select(WebhookDeliveryModel)
        if endpoint_id:
            statement = statement.where(
                WebhookDeliveryModel.webhook_endpoint_id == endpoint_id,
            )
        if emitter_id:
            statement = statement.join(
                WebhookEndpointModel,
                WebhookEndpointModel.id == WebhookDeliveryModel.webhook_endpoint_id,
            ).where(WebhookEndpointModel.emitter_id == emitter_id)
        if statuses:
            statement = statement.where(WebhookDeliveryModel.final_status.in_(statuses))
        statement = (
            statement.order_by(WebhookDeliveryModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [_delivery_to_domain(model) for model in self.session.scalars(statement)]


def _endpoint_to_domain(model: WebhookEndpointModel) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=model.id,
        emitter_id=model.emitter_id,
        url=model.url,
        secret_encrypted=model.secret_encrypted,
        event_subscriptions=model.event_subscriptions,
        is_active=model.is_active,
        retry_policy=model.retry_policy,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _delivery_to_domain(model: WebhookDeliveryModel) -> WebhookDelivery:
    return WebhookDelivery(
        id=model.id,
        webhook_endpoint_id=model.webhook_endpoint_id,
        event_type=model.event_type,
        payload_snapshot=model.payload_snapshot,
        attempt_number=model.attempt_number,
        request_at=model.request_at,
        response_code=model.response_code,
        response_body_snapshot=model.response_body_snapshot,
        final_status=model.final_status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
