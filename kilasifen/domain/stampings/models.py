"""Stamping domain models and selection rules."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from kilasifen.domain.common.errors import DomainInvariantError


@dataclass(slots=True)
class Stamping:
    """A timbrado configured for one emitter."""

    id: str
    emitter_id: str
    number: str
    start_date: date
    end_date: date | None
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime

    def is_valid_on(self, target_date: date) -> bool:
        """Return whether the stamping is valid for the target date."""

        if self.start_date > target_date:
            return False
        if self.end_date is not None and self.end_date < target_date:
            return False
        return True


def select_active_stamping(
    stampings: Iterable[Stamping],
    emitter_id: str,
    on_date: date,
) -> Stamping | None:
    """Select the single active and valid stamping for one emitter."""

    candidates = [
        stamping
        for stamping in stampings
        if stamping.emitter_id == emitter_id
        and stamping.is_active
        and stamping.is_valid_on(on_date)
    ]
    if len(candidates) > 1:
        raise DomainInvariantError(
            f"Emitter {emitter_id} has more than one active stamping for {on_date.isoformat()}."
        )
    if not candidates:
        return None
    return candidates[0]
