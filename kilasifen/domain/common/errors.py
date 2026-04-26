"""Domain-layer exceptions."""


class DomainError(Exception):
    """Base error for domain failures."""


class DomainInvariantError(DomainError):
    """Raised when a business invariant is broken."""


class NotFoundError(DomainError):
    """Raised when an expected domain object does not exist."""


class ConflictError(DomainError):
    """Raised when a uniqueness or state conflict occurs."""


class ServiceUnavailableError(DomainError):
    """Raised when a transient infrastructure dependency is unavailable."""
