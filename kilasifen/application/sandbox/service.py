"""Application policy for persisting deterministic sandbox directives."""

from copy import deepcopy
from typing import Any

from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.domain.sandbox import SandboxOutcome

SANDBOX_DIRECTIVE_KEY = "sandbox"
_SANDBOX_DIRECTIVE_VERSION = 1


class SandboxOutcomePolicy:
    """Attach and resolve sandbox directives behind the strict test boundary."""

    def __init__(self, runtime_environment: str):
        self.runtime_environment = runtime_environment

    def apply(
        self,
        payload_snapshot: dict[str, Any] | None,
        requested_outcome: SandboxOutcome | None,
    ) -> dict[str, Any] | None:
        """Return a copied snapshot with only a trusted sandbox directive."""

        snapshot = deepcopy(payload_snapshot)
        if snapshot is not None:
            snapshot.pop(SANDBOX_DIRECTIVE_KEY, None)

        if requested_outcome is None:
            return snapshot
        self._require_test_runtime()

        snapshot = snapshot or {}
        snapshot[SANDBOX_DIRECTIVE_KEY] = {
            "version": _SANDBOX_DIRECTIVE_VERSION,
            "outcome": requested_outcome.value,
        }
        return snapshot

    def resolve(self, payload_snapshot: dict[str, Any] | None) -> SandboxOutcome | None:
        """Resolve a persisted directive, refusing it outside the test runtime."""

        if not isinstance(payload_snapshot, dict):
            return None
        directive = payload_snapshot.get(SANDBOX_DIRECTIVE_KEY)
        if not isinstance(directive, dict):
            return None

        self._require_test_runtime()
        if directive.get("version") != _SANDBOX_DIRECTIVE_VERSION:
            raise UnprocessableEntityError("sandbox.directive_version_unsupported")
        try:
            return SandboxOutcome(str(directive["outcome"]))
        except (KeyError, ValueError) as exc:
            raise UnprocessableEntityError("sandbox.outcome_invalid") from exc

    def _require_test_runtime(self) -> None:
        if self.runtime_environment != "test":
            raise UnprocessableEntityError(
                "sandbox.test_runtime_required",
                details={"required_environment": "test"},
            )
