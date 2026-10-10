"""Explicit, scoped conversation memory for the credit assessment agent."""

import asyncio
from copy import deepcopy
from typing import TYPE_CHECKING

from agents.items import TResponseInputItem

from credit_monitoring.agents.events import EventStreamHandler
from credit_monitoring.domain.agent import AgentAnswer, SourceReference

if TYPE_CHECKING:
    from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent


class AgentConversation:
    """Retain successful SDK history until closed; accept one question at a time.

    Scope is fixed at construction. Exact close/done/quit messages close locally
    and return None. Blank questions raise ValueError, like single-question calls.
    """

    def __init__(
        self,
        agent: CreditAssessmentAgent,
        *,
        ticker: str | None = None,
        borrower_id: str | None = None,
    ) -> None:
        if borrower_id is not None and agent.assessment_service is None:
            raise ValueError("Configure an assessment_service before supplying a borrower ID.")
        self._agent = agent
        self._ticker = ticker
        self._borrower_id = borrower_id
        self._history: list[TResponseInputItem] = []
        self._sources: list[SourceReference] = []
        self._closed = False
        self._in_progress = False

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
        if self.closed:
            raise RuntimeError("Conversation is closed; start a new conversation.")
        if question.strip().casefold() in {"close", "done", "quit"}:
            self.close()
            return None
        if self._in_progress:
            raise RuntimeError("A question is already running in this conversation.")
        self._in_progress = True
        try:
            answer, history = await self._agent._run_question(
                question,
                self._ticker,
                borrower_id=self._borrower_id,
                event_stream_handler=event_stream_handler,
                history=deepcopy(self._history),
                sources=self._sources,
            )
            # Closing during a running question must never restore cleared memory.
            if not self.closed:
                self._history = history
                if answer.complete:
                    self._sources = [source.model_copy(deep=True) for source in answer.sources]
            return answer
        finally:
            self._in_progress = False
