"""Domain contract for deterministic sandbox document outcomes."""

from enum import Enum


class SandboxOutcome(str, Enum):
    """SIFEN outcomes integrations may request in the test runtime."""

    APPROVED = "approved"
    APPROVED_WITH_OBSERVATION = "approved_with_observation"
    REJECTED = "rejected"
