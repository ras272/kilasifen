"""Webhook repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint


class WebhookRepository(ABC):
    """Persistence contract for webhook endpoints and deliveries."""

    @abstractmethod
    def save_endpoint(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        """Persist a webhook endpoint."""

    @abstractmethod
    def get_endpoint(self, endpoint_id: str) -> WebhookEndpoint | None:
        """Load one webhook endpoint by id."""

    @abstractmethod
    def list_endpoints_for_emitter(self, emitter_id: str) -> list[WebhookEndpoint]:
        """List webhook endpoints for one emitter."""

    @abstractmethod
    def update_endpoint_for_emitter(
        self,
        *,
        endpoint_id: str,
        emitter_id: str,
        changes: dict[str, object],
    ) -> WebhookEndpoint | None:
        """Apply only the supplied endpoint columns and return the updated row."""

    @abstractmethod
    def save_delivery(self, delivery: WebhookDelivery) -> WebhookDelivery:
        """Persist one webhook delivery."""

    @abstractmethod
    def get_delivery(self, delivery_id: str) -> WebhookDelivery | None:
        """Load one webhook delivery by id."""

    @abstractmethod
    def list_recent_deliveries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        endpoint_id: str | None = None,
        emitter_id: str | None = None,
        statuses: list[str] | None = None,
    ) -> list[WebhookDelivery]:
        """List recent webhook deliveries with optional filters."""
