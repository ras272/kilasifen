"""Shared lifecycle guards for fiscal emitter operations."""

from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.repositories.emitters import EmitterRepository


def require_active_emitter(
    repository: EmitterRepository,
    emitter_id: str,
) -> None:
    """Lock and require an active emitter before sensitive side effects.

    The row lock lasts until the caller's transaction ends, so the caller must
    commit before any SIFEN network call. The wait for the lock is bounded
    (``emitters.lock_timeout``, a retryable ``503``).
    """

    _require_active(repository.get_status_for_update(emitter_id))


def require_active_emitter_without_lock(
    repository: EmitterRepository,
    emitter_id: str,
) -> None:
    """Require an active emitter without locking its row.

    For read-side SIFEN calls (queries and reconciliation), which must not
    hold the emitter lock while they wait on the network.
    """

    _require_active(repository.get_status(emitter_id))


def _require_active(status: str | None) -> None:
    if status is None:
        raise NotFoundError("emitters.not_found")
    if status != "active":
        raise ConflictError("emitters.inactive")
