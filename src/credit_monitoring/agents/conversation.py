"""Explicit, scoped conversation memory for the credit assessment agent."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from copy import deepcopy
from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelMessage

from credit_monitoring.agents.events import AgentEvent, EventStreamHandler
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.domain.agent import AgentAnswer, SourceReference
from credit_monitoring.observability import SessionContext
from credit_monitoring.observability.session import get_active_session

if TYPE_CHECKING:
    from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent


class AgentConversation:
    """Retain successful PydanticAI history until closed; accept one question at a time.

    Scope is fixed at construction. Exact close/done/quit messages close locally
    and return None. Blank questions raise ValueError, like single-question calls.
    """

    def __init__(
        self,
        agent: CreditAssessmentAgent,
        *,
        ticker: str | None = None,
        borrower_id: str | None = None,
        session: SessionContext | None = None,
    ) -> None:
        if borrower_id is not None and agent.assessment_service is None:
            raise ValueError("Configure an assessment_service before supplying a borrower ID.")
        self._agent = agent
        self._ticker = ticker
        self._borrower_id = borrower_id
        self._session = session if session is not None else get_active_session() or SessionContext()
        self._history: list[ModelMessage] = []
        self._sources: list[SourceReference] = []
        self._closed = False
        self._in_progress = False

    @property
    def session(self) -> SessionContext:
        """Retained telemetry identity used to query this conversation's costs."""
        return self._session

    @property
    def session_id(self) -> str:
        """Stable conversation identity, including across separate event loops."""
        return self._session.session_id

    @property
    def closed(self) -> bool:
        """Whether this conversation has ended and released its stored context."""
        return self._closed

    def close(self) -> None:
        """End the conversation and discard its history and evidence references."""
        self._closed = True
        self._history.clear()
        self._sources.clear()

    def ask(
        self,
        question: str,
        *,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AgentAnswer | None:
        """Ask synchronously; use await conversation.ask_async(...) in notebooks."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ask_async(question, event_stream_handler=event_stream_handler))
        raise RuntimeError(
            "An event loop is already running; use await conversation.ask_async(...)."
        )

    async def ask_async(
        self,
        question: str,
        *,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AgentAnswer | None:
        """Answer with prior context, or return None for a local closing command."""
        answer = None
        async with aclosing(
            self.stream_async(question, event_stream_handler=event_stream_handler)
        ) as stream:
            async for event in stream:
                if event.kind == "run_end":
                    answer = event.answer
        return answer

    async def stream_async(
        self,
        question: str,
        *,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream a turn; direct consumers must use contextlib.aclosing for early exits."""
        if self.closed:
            raise RuntimeError("Conversation is closed; start a new conversation.")
        if question.strip().casefold() in {"close", "done", "quit"}:
            self.close()
            return
        if self._in_progress:
            raise RuntimeError("A question is already running in this conversation.")
        self._in_progress = True
        state = AgentRunState(
            max_tool_rounds=self._agent.max_tool_rounds,
            sources={(s.document_id, s.citation): s.model_copy(deep=True) for s in self._sources},
        )
        try:
            async with aclosing(
                self._agent._stream_question(
                    question,
                    state,
                    self._ticker,
                    borrower_id=self._borrower_id,
                    event_stream_handler=event_stream_handler,
                    history=deepcopy(self._history),
                    session=self._session,
                )
            ) as stream:
                async for event in stream:
                    if event.kind == "run_end" and not self.closed:
                        self._history = deepcopy(state.history)
                        if event.answer.complete:
                            self._sources = [s.model_copy(deep=True) for s in event.answer.sources]
                    yield event
        finally:
            self._in_progress = False
