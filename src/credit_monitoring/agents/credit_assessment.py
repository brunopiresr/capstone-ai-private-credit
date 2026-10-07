"""Agents SDK orchestration for document research, calculations and risk predictions."""

import asyncio
import json

from agents import (
    Agent,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelResponse,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    Runner,
    Tool,
    ToolErrorFormatterArgs,
    ToolExecutionConfig,
)
from agents.tool_context import ToolContext
from openai import APIError, AsyncOpenAI, OpenAI

from credit_monitoring.agents.prompts.credit_assessment import CREDIT_ASSESSMENT_INSTRUCTIONS
from credit_monitoring.agents.responses_client import AgentFailure, ResponsesClientAdapter
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer


class _QuestionHooks(RunHooks[AgentRunState]):
    async def on_llm_end(
        self,
        context: RunContextWrapper[AgentRunState],
        agent: Agent[AgentRunState],
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

    async def on_tool_end(
        self,
        context: RunContextWrapper[AgentRunState],
        agent: Agent[AgentRunState],
        tool: Tool,
        result: object,
    ) -> None:
        if isinstance(context, ToolContext) and isinstance(result, str):
            context.context.record(
                context.tool_name,
                context.tool_call_id,
                context.tool_arguments,
                json.loads(result),
            )


def _unknown_tool_result(args: ToolErrorFormatterArgs[AgentRunState]) -> str:
    state = args.run_context.context
    return state.record(
        args.tool_name,
        args.call_id,
        state.arguments[args.call_id],
        {"ok": False, "error": "unknown_tool", "message": f"Unknown tool: {args.tool_name}"},
    )


class CreditAssessmentAgent:
    """Coordinate document evidence and optional borrower-scoped assessment services."""

    def __init__(
        self,
        *,
        client: OpenAI | AsyncOpenAI,
        service: DocumentProcessingService,
        assessment_service: AssessmentService | None = None,
        model: str = "gpt-4o-mini",
        max_tool_rounds: int = 6,
        tracing_enabled: bool = False,
    ) -> None:
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be positive.")
        self.client = client
        self.service = service
        self.assessment_service = assessment_service
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.tracing_enabled = tracing_enabled

    def ask(
        self, question: str, ticker: str | None = None, *, borrower_id: str | None = None
    ) -> AgentAnswer:
        """Run from synchronous application code; use ask_async in notebooks."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ask_async(question, ticker, borrower_id=borrower_id))
        raise RuntimeError("An event loop is already running; use await agent.ask_async(...).")

    async def ask_async(
        self, question: str, ticker: str | None = None, *, borrower_id: str | None = None
    ) -> AgentAnswer:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        state = AgentRunState(max_tool_rounds=self.max_tool_rounds)
        documents = DocumentTools(self.service, ticker=ticker)
        tools = documents.tools
        if borrower_id is not None:
            if self.assessment_service is None:
                raise ValueError("Configure an assessment_service before supplying a borrower ID.")
            assessments = AssessmentTools(self.assessment_service, borrower_id=borrower_id)
            tools += assessments.tools
        # Each question owns its tools and trace, so issuer/borrower scope and evidence do
        # not leak between calls. The SDK owns history and the execution loop.
        agent = Agent[AgentRunState](
            name="Credit assessment agent",
            instructions=CREDIT_ASSESSMENT_INSTRUCTIONS,
            model=OpenAIResponsesModel(
                model=self.model, openai_client=ResponsesClientAdapter(self.client)
            ),
            model_settings=ModelSettings(parallel_tool_calls=False),
            tools=tools,
        )
        try:
            result = await Runner.run(
                agent,
                input=json.dumps(
                    {"question": question, "ticker": ticker, "borrower_id": borrower_id}
                ),
                context=state,
                hooks=_QuestionHooks(),
                max_turns=self.max_tool_rounds + 1,
                run_config=RunConfig(
                    workflow_name="Credit assessment",
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
