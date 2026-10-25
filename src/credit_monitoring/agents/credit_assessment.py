"""Scoped PydanticAI agent facade over document and assessment services."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing

from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings

from credit_monitoring.agents.conversation import AgentConversation
from credit_monitoring.agents.events import AgentEvent, EventStreamHandler
from credit_monitoring.agents.models import DEFAULT_MODEL, resolve_model
from credit_monitoring.agents.prompts.credit_assessment import (
    build_credit_assessment_instructions,
)
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.streaming import run_stream
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer, AnswerContent
from credit_monitoring.observability import SessionContext, session_scope
from credit_monitoring.observability.configuration import capture_content_enabled, span


class CreditAssessmentAgent:
    """Configure tools and scope; streaming, history and display have separate owners."""

    def __init__(
        self,
        *,
        service: DocumentProcessingService | None = None,
        assessment_service: AssessmentService | None = None,
        model: Model | str = DEFAULT_MODEL,
        max_tool_rounds: int = 6,
        tracing_enabled: bool | None = None,
        name: str = "Credit assessment agent",
        event_stream_handler: EventStreamHandler | None = None,
        document_tool_names: frozenset[str] | None = None,
    ) -> None:
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be positive.")
        if service is None and assessment_service is None:
            raise ValueError("Configure a document or assessment service.")
        if document_tool_names is not None:
            known = {
                "list_documents",
                "get_document_extraction",
                "search_evidence",
                "process_document",
            }
            if unknown := document_tool_names - known:
                raise ValueError(f"Unknown document tools: {sorted(unknown)}")
        self.service = service
        self.assessment_service = assessment_service
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.tracing_enabled = tracing_enabled
        self.name = name
        self.event_stream_handler = event_stream_handler
        self.document_tool_names = (
            frozenset(document_tool_names) if document_tool_names is not None else None
        )

    def start_conversation(
        self,
        *,
        ticker: str | None = None,
        borrower_id: str | None = None,
        session: SessionContext | None = None,
    ) -> AgentConversation:
        self._validate_scope(ticker, borrower_id)
        return AgentConversation(self, ticker=ticker, borrower_id=borrower_id, session=session)

    def _validate_scope(self, ticker: str | None, borrower_id: str | None) -> None:
        if self.service is None:
            if not borrower_id or not borrower_id.strip():
                raise ValueError("Assessment-only conversations require an explicit borrower ID.")
            if ticker is not None:
                raise ValueError("Ticker scope requires a document service.")

    def ask(
        self,
        question: str,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AgentAnswer:
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
        answer = None
        async with aclosing(
            self.stream_async(
                question, ticker, borrower_id=borrower_id, event_stream_handler=event_stream_handler
            )
        ) as stream:
            async for event in stream:
                if event.kind == "run_end":
                    answer = event.answer
        assert answer is not None
        return answer

    async def stream_async(
        self,
        question: str,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream a question; direct consumers must use contextlib.aclosing on early exits."""
        state = AgentRunState(max_tool_rounds=self.max_tool_rounds)
        async with aclosing(
            self._stream_question(
                question,
                state,
                ticker,
                borrower_id=borrower_id,
                event_stream_handler=event_stream_handler,
            )
        ) as stream:
            async for event in stream:
                yield event

    async def _stream_question(
        self,
        question: str,
        state: AgentRunState,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        history: list[ModelMessage] | None = None,
        event_stream_handler: EventStreamHandler | None = None,
        session: SessionContext | None = None,
    ) -> AsyncIterator[AgentEvent]:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        self._validate_scope(ticker, borrower_id)
        tools = DocumentTools(self.service, ticker=ticker).tools if self.service else []
        if self.document_tool_names is not None:
            tools = [tool for tool in tools if tool.name in self.document_tool_names]
        if borrower_id is not None:
            if self.assessment_service is None:
                raise ValueError("Configure an assessment_service before supplying a borrower ID.")
            tools += AssessmentTools(self.assessment_service, borrower_id=borrower_id).tools
        agent = Agent(
            resolve_model(self.model),
            name=self.name,
            instructions=build_credit_assessment_instructions(
                assessment_enabled=borrower_id is not None
            ),
            output_type=ToolOutput(AnswerContent, name="final_result", strict=True),
            tools=tools,
            end_strategy="exhaustive",
            retries={"tools": self.max_tool_rounds, "output": 1},
            model_settings={"parallel_tool_calls": False},
        )
        if self.tracing_enabled is not None:
            agent.instrument = (
                InstrumentationSettings(
                    include_content=capture_content_enabled(), include_binary_content=False
                )
                if self.tracing_enabled
                else False
            )

        @agent.output_validator
        async def validate_answer(ctx: RunContext, output: AnswerContent) -> AnswerContent:
            if not ctx.partial_output and (
                not output.answer.strip()
                or output.confidence is None
                or not output.confidence_explanation.strip()
            ):
                raise ModelRetry(
                    "Provide a nonblank answer, confidence, and confidence_explanation."
                )
            return output

        handler = (
            event_stream_handler if event_stream_handler is not None else self.event_stream_handler
        )
        prompt = json.dumps({"question": question, "ticker": ticker, "borrower_id": borrower_id})
        with session_scope(session), span("agent.turn"):
            async with aclosing(
                run_stream(agent, prompt, state, history, tool_names={tool.name for tool in tools})
            ) as stream:
                async for event in stream:
                    if handler is not None:
                        await handler(event.model_copy(deep=True))
                    yield event
