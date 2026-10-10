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
from agents.items import TResponseInputItem
from agents.tool_context import ToolContext
from openai import APIError, AsyncOpenAI, OpenAI

from credit_monitoring.agents.conversation import AgentConversation
from credit_monitoring.agents.events import AgentEvent, EventStreamHandler
from credit_monitoring.agents.prompts.credit_assessment import CREDIT_ASSESSMENT_INSTRUCTIONS
from credit_monitoring.agents.responses_client import AgentFailure, ResponsesClientAdapter
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer, SourceReference


class _QuestionHooks(RunHooks[AgentRunState]):
    def __init__(self, event_stream_handler: EventStreamHandler | None = None) -> None:
        self.event_stream_handler = event_stream_handler

    async def emit(self, context: RunContextWrapper[AgentRunState], event: AgentEvent) -> None:
        if self.event_stream_handler is not None:
            await self.event_stream_handler(context, event)

    async def on_llm_start(
        self,
        context: RunContextWrapper[AgentRunState],
        agent: Agent[AgentRunState],
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        await self.emit(context, AgentEvent("model_start", agent.name))

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

    async def on_tool_start(
        self,
        context: RunContextWrapper[AgentRunState],
        agent: Agent[AgentRunState],
        tool: Tool,
    ) -> None:
        if isinstance(context, ToolContext):
            await self.emit(
                context,
                AgentEvent(
                    "tool_call",
                    agent.name,
                    tool_name=context.tool_name,
                    call_id=context.tool_call_id,
                    arguments=context.tool_arguments,
                ),
            )

    async def on_tool_end(
        self,
        context: RunContextWrapper[AgentRunState],
        agent: Agent[AgentRunState],
        tool: Tool,
        result: object,
    ) -> None:
        if isinstance(context, ToolContext) and isinstance(result, str):
            outcome = json.loads(result)
            context.context.record(
                context.tool_name,
                context.tool_call_id,
                context.tool_arguments,
                outcome,
            )
            await self.emit(
                context,
                AgentEvent(
                    "tool_result",
                    agent.name,
                    tool_name=context.tool_name,
                    call_id=context.tool_call_id,
                    outcome=outcome,
                ),
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
        name: str = "Credit assessment agent",
        event_stream_handler: EventStreamHandler | None = None,
    ) -> None:
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be positive.")
        self.client = client
        self.service = service
        self.assessment_service = assessment_service
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.tracing_enabled = tracing_enabled
        self.name = name
        self.event_stream_handler = event_stream_handler

    def start_conversation(
        self,
        *,
        ticker: str | None = None,
        borrower_id: str | None = None,
    ) -> AgentConversation:
        """Start an independent in-memory conversation with fixed application scope."""
        return AgentConversation(self, ticker=ticker, borrower_id=borrower_id)

    def ask(
        self,
        question: str,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AgentAnswer:
        """Run from synchronous application code; use ask_async in notebooks."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.ask_async(
                    question,
                    ticker,
                    borrower_id=borrower_id,
                    event_stream_handler=event_stream_handler,
                )
            )
        raise RuntimeError("An event loop is already running; use await agent.ask_async(...).")

    async def ask_async(
        self,
        question: str,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AgentAnswer:
        """Answer one independent question without retaining conversation history."""
        answer, _ = await self._run_question(
            question,
            ticker,
            borrower_id=borrower_id,
            event_stream_handler=event_stream_handler,
        )
        return answer

    async def _run_question(
        self,
        question: str,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        event_stream_handler: EventStreamHandler | None = None,
        history: list[TResponseInputItem] | None = None,
        sources: list[SourceReference] | None = None,
    ) -> tuple[AgentAnswer, list[TResponseInputItem]]:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        state = AgentRunState(
            max_tool_rounds=self.max_tool_rounds,
            sources={
                (source.document_id, source.citation): source.model_copy(deep=True)
                for source in sources or []
            },
        )
        documents = DocumentTools(self.service, ticker=ticker)
        tools = documents.tools
        if borrower_id is not None:
            if self.assessment_service is None:
                raise ValueError("Configure an assessment_service before supplying a borrower ID.")
            assessments = AssessmentTools(self.assessment_service, borrower_id=borrower_id)
            tools += assessments.tools
        # Each question owns its tools, limits and trace. Only an explicit conversation
        # carries previous SDK history and source references into the next question.
        agent = Agent[AgentRunState](
            name=self.name,
            instructions=CREDIT_ASSESSMENT_INSTRUCTIONS,
            model=OpenAIResponsesModel(
                model=self.model, openai_client=ResponsesClientAdapter(self.client)
            ),
            model_settings=ModelSettings(parallel_tool_calls=False),
            tools=tools,
        )
        hooks = _QuestionHooks(
            event_stream_handler if event_stream_handler is not None else self.event_stream_handler
        )

        async def unknown_tool_result(args: ToolErrorFormatterArgs[AgentRunState]) -> str:
            await hooks.emit(
                args.run_context,
                AgentEvent(
                    "tool_call",
                    agent.name,
                    tool_name=args.tool_name,
                    call_id=args.call_id,
                    arguments=state.arguments[args.call_id],
                ),
            )
            result = _unknown_tool_result(args)
            await hooks.emit(
                args.run_context,
                AgentEvent(
                    "tool_result",
                    agent.name,
                    tool_name=args.tool_name,
                    call_id=args.call_id,
                    outcome=json.loads(result),
                ),
            )
            return result

        question_input = json.dumps(
            {"question": question, "ticker": ticker, "borrower_id": borrower_id}
        )
        user_message: TResponseInputItem = {"role": "user", "content": question_input}
        run_input = question_input if history is None else [*history, user_message]
        next_history: list[TResponseInputItem] = []
        try:
            result = await Runner.run(
                agent,
                input=run_input,
                context=state,
                hooks=hooks,
                max_turns=self.max_tool_rounds + 1,
                run_config=RunConfig(
                    workflow_name="Credit assessment",
                    tracing_disabled=not self.tracing_enabled,
                    trace_include_sensitive_data=False,
                    tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1),
                    tool_not_found_behavior="return_error_to_model",
                    tool_error_formatter=unknown_tool_result,
                ),
            )
        except AgentFailure as exc:
            answer = state.answer(str(exc), exc.code)
        except MaxTurnsExceeded:
            answer = state.answer("Processing stopped at the tool-round limit.", "tool_round_limit")
        except APIError as exc:
            answer = state.answer(f"Agent model request failed: {exc}", "model_error")
        except ModelBehaviorError as exc:
            answer = state.answer(f"Agent model response failed: {exc}", "model_error")
        else:
            text = result.final_output
            answer = (
                state.answer(text)
                if isinstance(text, str) and text.strip()
                else state.answer("Model returned no answer or tool calls.", "empty_response")
            )
            if history is not None and answer.complete:
                next_history = result.to_input_list()
        if history is not None and not answer.complete:
            # Failed runs may contain unmatched calls or partial outputs. Keep the
            # prior successful history and a plain failure exchange instead.
            next_history = [
                *history,
                user_message,
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"answer": answer.answer, "complete": False, "error": answer.error}
                    ),
                },
            ]
        await hooks.emit(
            RunContextWrapper(context=state),
            AgentEvent("run_end", agent.name, error=answer.error),
        )
        return answer, next_history
