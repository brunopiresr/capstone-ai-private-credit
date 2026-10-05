"""Agents SDK orchestration for evidence-backed analyst questions."""

import asyncio
import json
from dataclasses import dataclass, field

from agents import (
    Agent,
    FunctionTool,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelResponse,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    Runner,
    ToolErrorFormatterArgs,
    ToolExecutionConfig,
)
from agents.tool_context import ToolContext
from openai import APIError, AsyncOpenAI, OpenAI

from credit_monitoring.agents.prompts.monitoring import MONITORING_INSTRUCTIONS
from credit_monitoring.agents.responses_client import AgentFailure, ResponsesClientAdapter
from credit_monitoring.agents.tools.documents import DocumentTools, decode_arguments
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer, SourceReference, ToolExecution


@dataclass
class _QuestionState:
    tools: DocumentTools
    max_tool_rounds: int
    tool_rounds: int = 0
    trace: list[ToolExecution] = field(default_factory=list)
    sources: dict[tuple[str, str], SourceReference] = field(default_factory=dict)
    arguments: dict[str, str] = field(default_factory=dict)

    def execute(self, name: str, call_id: str, raw_arguments: str) -> str:
        arguments = decode_arguments(raw_arguments)
        outcome = self.tools.execute(name, arguments)
        self.trace.append(
            ToolExecution(call_id=call_id, name=name, arguments=arguments, outcome=outcome)
        )
        for source in outcome.get("sources", []):
            reference = SourceReference(**source)
            self.sources[(reference.document_id, reference.citation)] = reference
        return json.dumps(outcome, ensure_ascii=False)

    def answer(self, text: str, error: str | None = None) -> AgentAnswer:
        return AgentAnswer(
            answer=text,
            complete=error is None,
            error=error,
            sources=list(self.sources.values()),
            tool_trace=self.trace,
        )


class _QuestionHooks(RunHooks[_QuestionState]):
    async def on_llm_end(
        self,
        context: RunContextWrapper[_QuestionState],
        agent: Agent[_QuestionState],
        response: ModelResponse,
    ) -> None:
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return
        state = context.context
        # Check before SDK dispatch: the last model turn may answer, but may not
        # execute any more tools. Count rounds, not individual calls in a round.
        if state.tool_rounds == state.max_tool_rounds:
            raise AgentFailure(
                "Processing stopped at the tool-round limit. The question is not fully answered; "
                "available sources and executed tools are attached.",
                "tool_round_limit",
            )
        state.tool_rounds += 1
        state.arguments = {call.call_id: call.arguments for call in calls}


async def _invoke_document_tool(context: ToolContext[_QuestionState], arguments: str) -> str:
    # Services are synchronous and may download/process documents. Keep that work
    # off the event loop; the runner limits local function concurrency to one.
    return await asyncio.to_thread(
        context.context.execute, context.tool_name, context.tool_call_id, arguments
    )


def _unknown_tool_result(args: ToolErrorFormatterArgs[_QuestionState]) -> str:
    state = args.run_context.context
    return state.execute(args.tool_name, args.call_id, state.arguments[args.call_id])


class MonitoringAgent:
    def __init__(
        self,
        *,
        client: OpenAI | AsyncOpenAI,
        service: DocumentProcessingService,
        model: str = "gpt-4o-mini",
        max_tool_rounds: int = 6,
        tracing_enabled: bool = False,
    ) -> None:
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be positive.")
        self.client = client
        self.service = service
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.tracing_enabled = tracing_enabled

    def ask(self, question: str, ticker: str | None = None) -> AgentAnswer:
        """Run from synchronous application code; use ask_async in notebooks."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ask_async(question, ticker))
        raise RuntimeError("An event loop is already running; use await agent.ask_async(...).")

    async def ask_async(self, question: str, ticker: str | None = None) -> AgentAnswer:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        state = _QuestionState(DocumentTools(self.service, ticker=ticker), self.max_tool_rounds)
        # Each question owns its tools and trace, so issuer scope and evidence do
        # not leak between calls. The SDK owns history and the execution loop.
        agent = Agent[_QuestionState](
            name="Credit monitoring agent",
            instructions=MONITORING_INSTRUCTIONS,
            model=OpenAIResponsesModel(
                model=self.model, openai_client=ResponsesClientAdapter(self.client)
            ),
            model_settings=ModelSettings(parallel_tool_calls=False),
            tools=[
                FunctionTool(
                    name=definition["name"],
                    description=definition["description"],
                    params_json_schema=definition["parameters"],
                    on_invoke_tool=_invoke_document_tool,
                )
                for definition in state.tools.definitions
            ],
        )
        try:
            result = await Runner.run(
                agent,
                input=json.dumps({"question": question, "ticker": ticker}),
                context=state,
                hooks=_QuestionHooks(),
                max_turns=self.max_tool_rounds + 1,
                run_config=RunConfig(
                    workflow_name="Credit monitoring",
                    tracing_disabled=not self.tracing_enabled,
                    trace_include_sensitive_data=False,
                    tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1),
                    tool_not_found_behavior="return_error_to_model",
                    tool_error_formatter=_unknown_tool_result,
                ),
            )
        except AgentFailure as exc:
            return state.answer(str(exc), exc.code)
        except MaxTurnsExceeded:
            return state.answer("Processing stopped at the tool-round limit.", "tool_round_limit")
        except APIError as exc:
            return state.answer(f"Agent model request failed: {exc}", "model_error")
        except ModelBehaviorError as exc:
            return state.answer(f"Agent model response failed: {exc}", "model_error")
        text = result.final_output
        if not isinstance(text, str) or not text.strip():
            return state.answer("Model returned no answer or tool calls.", "empty_response")
        return state.answer(text)
