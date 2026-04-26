"""Domain-layer exceptions."""


class DomainError(Exception):
    """Base error for domain failures."""


class DomainInvariantError(DomainError):
    """Raised when a business invariant is broken."""


class NotFoundError(DomainError):
    """Raised when an expected domain object does not exist."""


class ConflictError(DomainError):
    """Raised when a uniqueness or state conflict occurs."""

    def __init__(self, code: str, details: dict | None = None):
        super().__init__(code)
        self.code = code
        self.details = details

    def __str__(self) -> str:
        return self.code


class UnprocessableEntityError(DomainError):
    """Raised when a request is syntactically valid but semantically invalid."""

    def __init__(self, code: str, details: dict | None = None):
        super().__init__(code)
        self.code = code
        self.details = details

    def __str__(self) -> str:
        return self.code


class ServiceUnavailableError(DomainError):
    """Raised when a transient infrastructure dependency is unavailable."""
