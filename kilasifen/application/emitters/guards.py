"""Shared lifecycle guards for fiscal emitter operations."""

from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.repositories.emitters import EmitterRepository


def require_active_emitter(
    repository: EmitterRepository,
    emitter_id: str,
) -> None:
    """Lock and require an active emitter before sensitive side effects."""

    status = repository.get_status_for_update(emitter_id)
    if status is None:
        raise NotFoundError("emitters.not_found")
    if status != "active":
        raise ConflictError("emitters.inactive")
