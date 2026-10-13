"""One graph execution path for streamed and completed agent answers."""

import json
from collections.abc import AsyncIterator

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
from pydantic_ai.usage import UsageLimits

from credit_monitoring.agents.events import AgentEvent
from credit_monitoring.agents.models import ModelFailure, check_response
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.domain.agent import AnswerContent


async def run_stream(
    agent: Agent[None, AnswerContent],
    prompt: str,
    state: AgentRunState,
    history: list[ModelMessage] | None = None,
    *,
    tool_names: set[str],
) -> AsyncIterator[AgentEvent]:
    """Translate framework events; accept final output only after the graph completes."""
    name = agent.name or "Credit assessment agent"
    calls: dict[str, ToolCallPart] = {}
    try:
        async with agent.iter(
            prompt,
            message_history=history,
            usage_limits=UsageLimits(request_limit=state.max_tool_rounds + 1),
        ) as run:
            try:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        yield AgentEvent(kind="model_start", agent_name=name)
                        async with node.stream(run.ctx) as stream:
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
                    elif Agent.is_call_tools_node(node):
                        check_response(node.model_response)
                        service_calls = [
                            part
                            for part in node.model_response.parts
                            if isinstance(part, ToolCallPart) and part.tool_name != "final_result"
                        ]
                        if service_calls:
                            if state.tool_rounds >= state.max_tool_rounds:
                                raise ModelFailure(
                                    "Processing stopped at the tool-round limit.",
                                    "tool_round_limit",
                                )
                            state.tool_rounds += 1
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                if isinstance(event, FunctionToolCallEvent):
                                    part = event.part
                                    calls[part.tool_call_id] = part
                                    yield AgentEvent(
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
                                        outcome = {
                                            "ok": False,
                                            "error": "invalid_arguments"
                                            if call.tool_name in tool_names
                                            else "unknown_tool",
                                            "message": part.model_response(),
                                        }
                                    else:
                                        outcome = (
                                            json.loads(part.content)
                                            if isinstance(part.content, str)
                                            else part.content
                                        )
                                    state.record(
                                        call.tool_name,
                                        call.tool_call_id,
                                        call.args_as_json_str(),
                                        outcome,
                                    )
                                    yield AgentEvent(
                                        kind="tool_result",
                                        agent_name=name,
                                        tool_name=call.tool_name,
                                        call_id=call.tool_call_id,
                                        outcome=outcome,
                                    )
            except GeneratorExit:
                # Close the graph normally when a UI stops consuming the generator.
                # No further nodes execute and no provisional history is committed.
                return
            assert run.result is not None
            answer = state.answer(run.result.output)
            state.history = run.result.all_messages()
    except ModelFailure as exc:
        answer = state.answer(str(exc), exc.code)
    except UsageLimitExceeded:
        answer = state.answer("Processing stopped at the tool-round limit.", "tool_round_limit")
    except (ModelAPIError, UnexpectedModelBehavior) as exc:
        answer = state.answer(f"Agent model request/response failed: {exc}", "model_error")
    if history is not None and not answer.complete:
        state.history = [
            *history,
            ModelRequest(parts=[UserPromptPart(prompt)]),
            # Only a plain failure exchange survives; partial tool sequences do not.
            ModelResponse(
                parts=[
                    TextPart(
                        json.dumps(
                            {"answer": answer.answer, "complete": False, "error": answer.error}
                        )
                    )
                ]
            ),
        ]
    yield AgentEvent(kind="run_end", agent_name=name, answer=answer, error=answer.error)
