"""Live agent progress callbacks, independent of notebook display and SDK tracing."""

from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agents import RunContextWrapper

from credit_monitoring.agents.run_state import AgentRunState


@dataclass(frozen=True)
class AgentEvent:
    """A model request, permitted tool call, tool outcome, or terminal run status."""

    kind: Literal["model_start", "tool_call", "tool_result", "run_end"]
    agent_name: str
    tool_name: str | None = None
    call_id: str | None = None
    arguments: str | None = None
    outcome: dict[str, Any] | None = None
    error: str | None = None


EventStreamHandler = Callable[[RunContextWrapper[AgentRunState], AgentEvent], Awaitable[None]]


class NamedAgent(Protocol):
    name: str


class AgentEventCallback:
    """Print live progress; optionally label it with a supplied agent's name.

    Accepts individual events or nested async event streams. Tool outcomes are
    summarized rather than printing entire documents or private model reasoning.
    """

    def __init__(self, agent: NamedAgent | None = None) -> None:
        self.agent = agent

    async def print_function_calls(
        self,
        ctx: RunContextWrapper[AgentRunState],
        event: AgentEvent | AsyncIterable,
    ) -> None:
        if isinstance(event, AsyncIterable):
            async for sub in event:
                await self.print_function_calls(ctx, sub)
            return

        name = self.agent.name if self.agent is not None else event.agent_name
        # if event.kind == "model_start":
        #    message = f"MODEL REQUEST ({name})"
        if event.kind == "tool_call":
            message = f"TOOL CALL ({name}): {event.tool_name}({event.arguments})"
        elif event.kind == "tool_result":
            outcome = event.outcome or {}
            status = "ok" if outcome.get("ok") else f"error: {outcome.get('error', 'unknown')}"
            message = f"TOOL RESULT ({name}): {event.tool_name} — {status}"
        else:
            status = f"incomplete: {event.error}" if event.error else "complete"
            message = f"AGENT FINISHED ({name}): {status}"
        print(message, flush=True)

    async def __call__(
        self,
        ctx: RunContextWrapper[AgentRunState],
        event: AgentEvent | AsyncIterable,
    ) -> None:
        await self.print_function_calls(ctx, event)
