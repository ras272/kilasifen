"""How the platform reads a failed SIFEN submission (documents and events).

Application policy over the engine error types: it decides whether a failed
submission may be sent again as is or must be resolved as uncertain.
"""

from __future__ import annotations

from kilasifen.engine.sdk.errors import (
    SifenError,
    SifenRequestNotSentError,
    SifenTransportClosedError,
)

#: Failures the engine raises before writing any byte of the request.
_NOT_SENT_ERRORS = (SifenRequestNotSentError, SifenTransportClosedError)


def request_never_left(exc: BaseException) -> bool:
    """Tell whether ``exc`` proves the request did not reach SIFEN.

    Only then is sending the same request again harmless. Every other failure
    of a submission (timeouts, dropped connections, SOAP faults, unreadable
    answers, programming errors) may have happened after SIFEN received the
    request, so its outcome is unknown.
    """

    return isinstance(exc, _NOT_SENT_ERRORS)


def describe_submission_failure(exc: BaseException) -> str:
    """Short, data-free description of a failed submission.

    Engine errors carry curated messages. Anything else is reduced to its
    type, because its text may quote request or response content.
    """

    if isinstance(exc, SifenError):
        return str(exc)
    return f"{type(exc).__name__}: unexpected error while submitting to SIFEN"
