"""Row-lock helpers shared by the SQLAlchemy repositories."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import Select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from kilasifen.domain.common.errors import ServiceUnavailableError

_T = TypeVar("_T")

#: SQLSTATE values PostgreSQL reports when a lock wait is cut short:
#: ``lock_not_available`` (``lock_timeout``) and ``query_canceled``.
_LOCK_TIMEOUT_SQLSTATES = frozenset({"55P03", "57014"})


def backend_name(session: Session) -> str:
    """Dialect name of the database bound to ``session`` (``""`` if unbound)."""

    bind = session.get_bind()
    if bind is None:
        return ""
    return bind.dialect.name


def locked_fresh(statement: Select) -> Select:
    """Turn a ``SELECT`` into ``SELECT ... FOR UPDATE`` that reloads the rows.

    ``populate_existing`` makes the session overwrite objects it already had
    in its identity map, so the caller sees the committed state that the lock
    protects and not a copy loaded earlier in the transaction. SQLite ignores
    ``FOR UPDATE``; its writers are serialized by the database file lock.
    """

    return statement.with_for_update().execution_options(populate_existing=True)


def is_lock_timeout(exc: OperationalError) -> bool:
    """Tell whether a PostgreSQL error was a lock wait that ran out of time."""

    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate in _LOCK_TIMEOUT_SQLSTATES


def run_with_lock_timeout(
    session: Session,
    operation: Callable[[], _T],
    *,
    timeout_ms: int,
    error_code: str,
) -> _T:
    """Run ``operation`` waiting at most ``timeout_ms`` for row locks.

    On PostgreSQL the bound is set with ``set_config('lock_timeout', ...,
    true)`` (transaction-local) and the previous value is restored once
    ``operation`` succeeds, so later statements of the same transaction keep
    their usual behaviour. A lock wait that runs out of time raises
    :class:`ServiceUnavailableError` with ``error_code``, which the API turns
    into a retryable ``503``; the transaction is then aborted and must be
    rolled back. Other backends run ``operation`` unchanged: SQLite has no
    row locks and relies on its own busy timeout.
    """

    if backend_name(session) != "postgresql":
        return operation()

    previous = session.scalar(text("SELECT current_setting('lock_timeout')"))
    _set_local_lock_timeout(session, f"{int(timeout_ms)}ms")
    try:
        result = operation()
    except OperationalError as exc:
        if is_lock_timeout(exc):
            raise ServiceUnavailableError(error_code) from exc
        raise
    _set_local_lock_timeout(session, str(previous))
    return result


def _set_local_lock_timeout(session: Session, value: str) -> None:
    session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": value},
    )
