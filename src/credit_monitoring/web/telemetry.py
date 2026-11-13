"""Browser-session correlation without a shared parent span or process-global identity."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import uuid4

import logfire
import streamlit as st

WEB_SESSION_KEY = "_telemetry_web_session_id"


@contextmanager
def web_session_scope() -> Iterator[str]:
    """Bind one Streamlit session's UUID, including in callbacks and fragment reruns.

    Use as a context manager or a decorator on synchronous UI entrypoints. Tasks and
    asyncio.to_thread workers inherit the baggage; every exit restores caller context.
    """
    if WEB_SESSION_KEY not in st.session_state:
        st.session_state[WEB_SESSION_KEY] = str(uuid4())
    session_id = st.session_state[WEB_SESSION_KEY]
    with logfire.set_baggage(**{"session.id": session_id}):
        yield session_id


def with_web_session[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Bind identity for a synchronous page, callback, or independently rerun fragment."""
    return web_session_scope()(function)
