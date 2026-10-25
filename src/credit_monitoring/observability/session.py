"""Retain session identity and resume its completed anchor between execution scopes."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

import logfire

from credit_monitoring.observability.configuration import is_observability_configured


@dataclass
class SessionContext:
    """One conversation's identity and internal Logfire propagation state."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    carrier: dict[str, str] | None = field(default=None, repr=False)


_current_session: ContextVar[SessionContext | None] = ContextVar(
    "credit_monitoring_session", default=None
)


def get_active_session() -> SessionContext | None:
    """Read active application identity without altering trace parentage."""
    return _current_session.get()


@logfire.instrument("agent.session", new_trace=True, extract_args=False)
def _capture_session_trace() -> dict[str, str]:
    return logfire.get_context()


@contextmanager
def session_scope(session: SessionContext | None = None) -> Iterator[SessionContext]:
    """Preserve nested parents; restore caller context after every execution scope."""
    current = get_active_session()
    if current is not None and (session is None or session is current):
        yield current
        return

    session = session if session is not None else SessionContext()
    token = _current_session.set(session)
    try:
        if not is_observability_configured():
            yield session
            return
        with logfire.set_baggage(**{"gen_ai.conversation.id": session.session_id}):
            if session.carrier is None:
                session.carrier = _capture_session_trace()
            with logfire.attach_context(session.carrier):
                yield session
    finally:
        _current_session.reset(token)
