"""Stamping application service layer."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.stampings.models import Stamping
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.stampings import StampingRepository


class StampingService:
    """Use cases for stamping management."""

    def __init__(
        self,
        stamping_repository: StampingRepository,
        emitter_repository: EmitterRepository,
    ):
        self.stamping_repository = stamping_repository
        self.emitter_repository = emitter_repository

    def create_stamping(
        self,
        *,
        emitter_id: str,
        number: str,
        start_date: date,
        end_date: date | None,
    ) -> Stamping:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        if end_date is not None and end_date < start_date:
            raise ConflictError("stampings.invalid_date_window")

        timestamp = _now()
        stamping = Stamping(
            id=str(uuid4()),
            emitter_id=emitter_id,
            number=number,
            start_date=start_date,
            end_date=end_date,
            is_active=False,
            status="inactive",
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self.stamping_repository.save(stamping)

    def list_stampings(self, emitter_id: str) -> list[Stamping]:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        return self.stamping_repository.list_for_emitter(emitter_id)

    def activate_stamping(self, stamping_id: str) -> Stamping:
        target = self.stamping_repository.get(stamping_id)
        if target is None:
            raise NotFoundError("stampings.not_found")

        stampings = self.stamping_repository.list_for_emitter(target.emitter_id)
        activated: Stamping | None = None
        self.stamping_repository.deactivate_others(target.emitter_id, stamping_id)
        for stamping in stampings:
            updated = replace(
                stamping,
                is_active=stamping.id == stamping_id,
                status="active" if stamping.id == stamping_id else "inactive",
                updated_at=_now(),
            )
            saved = self.stamping_repository.save(updated)
            if saved.id == stamping_id:
                activated = saved

        if activated is None:
            raise ConflictError("stampings.activation_failed")
        return activated


def _now() -> datetime:
    return datetime.now(UTC)
