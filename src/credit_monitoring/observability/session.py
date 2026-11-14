"""Correlate sessions and chat traces without leaving context attached while idle."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import logfire

from credit_monitoring.observability.configuration import is_observability_configured


@dataclass
class SessionContext:
    """One conversation's identity and display name, independent of trace lifetime."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = field(default="Credit assessment", kw_only=True)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC), kw_only=True)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Session name must not be blank.")
        if self.created_at.tzinfo is None:
            raise ValueError("Session creation time must include a timezone.")
        self.created_at = self.created_at.astimezone(UTC)


_current_session: ContextVar[SessionContext | None] = ContextVar(
    "credit_monitoring_session", default=None
)


def get_active_session() -> SessionContext | None:
    """Read active application identity without altering trace parentage."""
    return _current_session.get()


@contextmanager
def conversation_scope(session: SessionContext, parent: dict[str, str]) -> Iterator[None]:
    """Group turns under one chat anchor without keeping context attached while idle.

    The anchor covers the first turn. Later turns attach its serialized trace context,
    as with distributed requests; no live span or ContextVar token survives a turn.
    Only trace headers are retained so each turn keeps its current interaction baggage.
    """
    with session_scope(session):
        if not is_observability_configured():
            yield
        elif parent:
            with logfire.attach_context({**logfire.get_context(), **parent}):
                yield
        else:
            with logfire.span(
                "Chat session: {chat_name} [chat {chat_id}]",
                _span_name="agent.session",
                chat_name=session.name,
                chat_id=session.session_id,
            ):
                parent.update(
                    (key, value)
                    for key, value in logfire.get_context().items()
                    if key in {"traceparent", "tracestate"}
                )
                yield


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
            yield session
    finally:
        _current_session.reset(token)
