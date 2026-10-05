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


class FiscalRuleError(ValueError):
    """A fiscal payload breaks a named rule; ``code`` identifies the rule.

    It is a ``ValueError`` so the API request validators can raise it: the
    ``422 request.validation_failed`` entry of that field then carries
    ``code`` next to ``loc``, ``message`` and ``type``. ``message`` defaults
    to the code and never contains submitted values.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
