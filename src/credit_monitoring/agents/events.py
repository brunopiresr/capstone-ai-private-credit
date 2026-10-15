"""Serializable UI events and an optional console consumer."""

from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Literal, Protocol

from pydantic import ConfigDict, Field

from credit_monitoring.domain.agent import AgentAnswer, AnswerContent, SourceReference
from credit_monitoring.domain.base import ExtractionModel
from credit_monitoring.domain.tool_results import ToolFailure, ToolOutcome


class AgentEvent(ExtractionModel):
    """Public progress; output snapshots are provisional until run_end."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["model_start", "tool_call", "tool_result", "answer_update", "run_end"]
    agent_name: str
    tool_name: str | None = None
    call_id: str | None = None
    arguments: str | None = None
    outcome: ToolOutcome | None = None
    sources: list[SourceReference] = Field(default_factory=list)
    output: AnswerContent | None = None
    answer: AgentAnswer | None = None
    error: str | None = None


EventStreamHandler = Callable[[AgentEvent], Awaitable[None]]


class NamedAgent(Protocol):
    name: str


class AgentEventCallback:
    """Print progress without exposing full tool payloads or private reasoning."""

    def __init__(self, agent: NamedAgent | None = None) -> None:
        self.agent = agent

    async def print_function_calls(self, event: AgentEvent | AsyncIterable[AgentEvent]) -> None:
        if isinstance(event, AsyncIterable):
            async for sub in event:
                await self.print_function_calls(sub)
            return
        name = self.agent.name if self.agent is not None else event.agent_name
        if event.kind == "model_start":
            message = f"MODEL REQUEST ({name})"
        elif event.kind == "tool_call":
            message = f"TOOL CALL ({name}): {event.tool_name}({event.arguments})"
        elif event.kind == "tool_result":
            if isinstance(event.outcome, ToolFailure):
                status = f"error: {event.outcome.code}"
            else:
                status = "ok" if event.outcome is not None else "error: unknown"
            message = f"TOOL RESULT ({name}): {event.tool_name} — {status}"
        elif event.kind == "answer_update":
            return  # UI consumers can render snapshots; console progress stays concise.
        else:
            status = f"incomplete: {event.error}" if event.error else "complete"
            message = f"AGENT FINISHED ({name}): {status}"
        print(message, flush=True)

    async def __call__(self, event: AgentEvent | AsyncIterable[AgentEvent]) -> None:
        await self.print_function_calls(event)
