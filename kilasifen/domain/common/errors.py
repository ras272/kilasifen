"""Domain-layer exceptions."""


class DomainError(Exception):
    """Base error for domain failures."""


class DomainInvariantError(DomainError):
    """Raised when a business invariant is broken."""
