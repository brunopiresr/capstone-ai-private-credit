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
    CONFIDENCE_INSTRUCTIONS,
    CREDIT_ASSESSMENT_INSTRUCTIONS,
)
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.streaming import run_stream
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer, AnswerContent


class CreditAssessmentAgent:
    """Configure tools and scope; streaming, history and display have separate owners."""

    def __init__(
        self,
        *,
        service: DocumentProcessingService,
        assessment_service: AssessmentService | None = None,
        model: Model | str = DEFAULT_MODEL,
        max_tool_rounds: int = 6,
        tracing_enabled: bool = False,
        name: str = "Credit assessment agent",
        event_stream_handler: EventStreamHandler | None = None,
    ) -> None:
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be positive.")
        self.service = service
        self.assessment_service = assessment_service
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.tracing_enabled = tracing_enabled
        self.name = name
        self.event_stream_handler = event_stream_handler

    def start_conversation(
        self, *, ticker: str | None = None, borrower_id: str | None = None
    ) -> AgentConversation:
        return AgentConversation(self, ticker=ticker, borrower_id=borrower_id)

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
    ) -> AsyncIterator[AgentEvent]:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        tools = DocumentTools(self.service, ticker=ticker).tools
        if borrower_id is not None:
            if self.assessment_service is None:
                raise ValueError("Configure an assessment_service before supplying a borrower ID.")
            tools += AssessmentTools(self.assessment_service, borrower_id=borrower_id).tools
        agent = Agent(
            resolve_model(self.model),
            name=self.name,
            instructions=CREDIT_ASSESSMENT_INSTRUCTIONS + CONFIDENCE_INSTRUCTIONS,
            output_type=ToolOutput(AnswerContent, name="final_result", strict=True),
            tools=tools,
            end_strategy="exhaustive",
            retries={"tools": self.max_tool_rounds, "output": 1},
            model_settings={"parallel_tool_calls": False},
        )
        agent.instrument = (
            InstrumentationSettings(include_content=False) if self.tracing_enabled else False
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
        async with aclosing(
            run_stream(agent, prompt, state, history, tool_names={tool.name for tool in tools})
        ) as stream:
            async for event in stream:
                if handler is not None:
                    await handler(event)
                yield event
