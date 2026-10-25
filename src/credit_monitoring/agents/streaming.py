"""One graph execution path for streamed and completed agent answers."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing

from pydantic import ValidationError
from pydantic_ai import (
    Agent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRetry,
)
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.result import AgentStream
from pydantic_ai.usage import UsageLimits

from credit_monitoring.agents.events import AgentEvent
from credit_monitoring.agents.models import ModelFailure, check_response
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.common import tool_outcome
from credit_monitoring.domain.agent import AgentAnswer, AnswerContent
from credit_monitoring.domain.tool_results import ToolFailure
from credit_monitoring.observability.session import get_active_session

logger = logging.getLogger(__name__)


async def _model_updates(
    stream: AgentStream[None, AnswerContent],
    name: str,
) -> AsyncIterator[AgentEvent]:
    """Emit copied provisional answers; graph validation still decides completion."""
    final_started = False
    async for event in stream:
        if isinstance(event, FinalResultEvent):
            final_started = True
            break
    if final_started:
        try:
            async for output in stream.stream_output(debounce_by=None):
                yield AgentEvent(
                    kind="answer_update",
                    agent_name=name,
                    output=output.model_copy(deep=True),
                )
        except UnexpectedModelBehavior as exc:
            # iter() continues into graph validation, where bounded output
            # retries are supported. Invalid output is never committed.
            if not isinstance(exc.__cause__, (ValidationError, ModelRetry)):
                raise
    check_response(stream.response)


def _count_tool_round(response: ModelResponse, state: AgentRunState) -> None:
    service_calls = [
        part
        for part in response.parts
        if isinstance(part, ToolCallPart) and part.tool_name != "final_result"
    ]
    if service_calls:
        if state.tool_rounds >= state.max_tool_rounds:
            raise ModelFailure(
                "Processing stopped at the tool-round limit.",
                "tool_round_limit",
            )
        state.tool_rounds += 1


def _tool_event(
    event: FunctionToolCallEvent | FunctionToolResultEvent,
    calls: dict[str, ToolCallPart],
    state: AgentRunState,
    tool_names: set[str],
    name: str,
) -> AgentEvent:
    """Record only executed outcomes and publish an isolated event snapshot."""
    if isinstance(event, FunctionToolCallEvent):
        part = event.part
        calls[part.tool_call_id] = part
        return AgentEvent(
            kind="tool_call",
            agent_name=name,
            tool_name=part.tool_name,
            call_id=part.tool_call_id,
            arguments=part.args_as_json_str(),
        )
    elif isinstance(event, FunctionToolResultEvent):
        part = event.part
        call = calls[part.tool_call_id]
        if isinstance(part, RetryPromptPart):
            logger.warning("Agent tool arguments rejected", extra={"tool_name": call.tool_name})
            outcome = ToolFailure(
                code="invalid_arguments" if call.tool_name in tool_names else "unknown_tool",
                message=part.model_response(),
            )
        else:
            outcome = tool_outcome(part.content)
        execution = state.record(
            call.tool_name,
            call.tool_call_id,
            call.args_as_json_str(),
            outcome,
        )
        return AgentEvent(
            kind="tool_result",
            agent_name=name,
            tool_name=call.tool_name,
            call_id=call.tool_call_id,
            outcome=execution.outcome,
            sources=execution.sources,
        ).model_copy(deep=True)


def _failure_history(
    history: list[ModelMessage],
    prompt: str,
    answer: AgentAnswer,
) -> list[ModelMessage]:
    return [
        *history,
        ModelRequest(parts=[UserPromptPart(prompt)]),
        # Only a plain failure exchange survives; partial tool sequences do not.
        ModelResponse(
            parts=[
                TextPart(
                    json.dumps({"answer": answer.answer, "complete": False, "error": answer.error})
                )
            ]
        ),
    ]


async def run_stream(
    agent: Agent[None, AnswerContent],
    prompt: str,
    state: AgentRunState,
    history: list[ModelMessage] | None = None,
    *,
    tool_names: set[str],
) -> AsyncIterator[AgentEvent]:
    """Translate one graph execution while preserving the public event/history contract.

    Answer updates are provisional; only run_end after graph completion commits
    successful history. Tool results contain executed provenance. Early close or
    cancellation commits no partial turn, and failed runs retain a plain failure
    exchange instead of unfinished tool sequences. Requests and tool rounds stay bounded.
    """
    name = agent.name or "Credit assessment agent"
    calls: dict[str, ToolCallPart] = {}
    session = get_active_session()
    try:
        async with agent.iter(
            prompt,
            message_history=history,
            conversation_id=session.session_id if session else None,
            usage_limits=UsageLimits(request_limit=state.max_tool_rounds + 1),
        ) as run:
            try:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        yield AgentEvent(kind="model_start", agent_name=name)
                        async with node.stream(run.ctx) as stream:
                            async with aclosing(_model_updates(stream, name)) as updates:
                                async for update in updates:
                                    yield update
                    elif Agent.is_call_tools_node(node):
                        check_response(node.model_response)
                        _count_tool_round(node.model_response, state)
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                if isinstance(
                                    event, (FunctionToolCallEvent, FunctionToolResultEvent)
                                ):
                                    yield _tool_event(event, calls, state, tool_names, name)
            except GeneratorExit:
                # Close the graph normally when a UI stops consuming the generator.
                # No further nodes execute and no provisional history is committed.
                return
            assert run.result is not None
            answer = state.answer(run.result.output)
            state.history = run.result.all_messages()
    except ModelFailure as exc:
        logger.error("Agent execution failed", extra={"error_code": exc.code})
        answer = state.answer(str(exc), exc.code)
    except UsageLimitExceeded:
        logger.warning("Agent execution stopped", extra={"error_code": "tool_round_limit"})
        answer = state.answer("Processing stopped at the tool-round limit.", "tool_round_limit")
    except (ModelAPIError, UnexpectedModelBehavior) as exc:
        logger.error("Agent model failed", extra={"error_type": type(exc).__name__})
        answer = state.answer(f"Agent model request/response failed: {exc}", "model_error")
    if history is not None and not answer.complete:
        state.history = _failure_history(history, prompt, answer)
    yield AgentEvent(kind="run_end", agent_name=name, answer=answer, error=answer.error)
