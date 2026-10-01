"""Best-effort webhook publication inside the caller's transaction."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from kilasifen.domain.documents.models import Document


class WebhookPublication(Protocol):
    """The publishing side of ``WebhookService``."""

    def publish_event(
        self,
        *,
        emitter_id: str,
        event_type: str,
        payload: dict | None,
    ) -> list[tuple]:
        """Fan out one event to the subscribed endpoints."""

    def publish_document_status(self, *, document: Document) -> list[tuple]:
        """Fan out the status event of ``document``."""


class SavepointWebhookPublisher:
    """Publish webhooks inside a SAVEPOINT of the current transaction.

    Callers treat publishing as best effort: they log its errors and go on.
    On PostgreSQL a failed statement aborts the whole transaction, and the
    later COMMIT quietly becomes a ROLLBACK, so a database error while
    publishing would discard what the caller was recording (for a worker,
    SIFEN's answer). The savepoint confines such an error, and any row the
    publication had written, to the publication.
    """

    def __init__(self, session: Session, publisher: WebhookPublication) -> None:
        self._session = session
        self._publisher = publisher

    def publish_event(
        self,
        *,
        emitter_id: str,
        event_type: str,
        payload: dict | None,
    ) -> list[tuple]:
        with self._session.begin_nested():
            return self._publisher.publish_event(
                emitter_id=emitter_id,
                event_type=event_type,
                payload=payload,
            )

    def publish_document_status(self, *, document: Document) -> list[tuple]:
        with self._session.begin_nested():
            return self._publisher.publish_document_status(document=document)
