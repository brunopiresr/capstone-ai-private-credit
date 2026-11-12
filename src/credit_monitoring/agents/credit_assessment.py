"""Scoped PydanticAI agent facade over document and assessment services."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput
from pydantic_ai.capabilities import PrepareOutputTools
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings
from pydantic_ai.tools import ToolDefinition

from credit_monitoring.agents.conversation import AgentConversation
from credit_monitoring.agents.events import AgentEvent, EventStreamHandler
from credit_monitoring.agents.models import DEFAULT_MODEL, resolve_model
from credit_monitoring.agents.prompts.credit_assessment import (
    build_credit_assessment_instructions,
)
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.source_tables import (
    SourceTableDraft,
    materialize_source_tables,
    source_table_schema,
)
from credit_monitoring.agents.streaming import run_stream
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.observability import SessionContext, session_scope
from credit_monitoring.observability.activity import activity_scope
from credit_monitoring.observability.configuration import capture_content_enabled, span


def current_local_date() -> date:
    return datetime.now(ZoneInfo("Europe/Lisbon")).date()


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
        if borrower_id is not None:
            if self.assessment_service is None:
                raise ValueError("Configure an assessment_service before supplying a borrower ID.")
            if not borrower_id.strip():
                raise ValueError("An explicit borrower ID is required.")
        if self.service is None and ticker is not None:
            raise ValueError("Ticker scope requires a document service.")

    def ask(
        self,
        question: str,
        ticker: str | None = None,
        *,
        borrower_id: str | None = None,
        selected_dates: tuple[date, date] | None = None,
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
                    selected_dates=selected_dates,
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
        selected_dates: tuple[date, date] | None = None,
        event_stream_handler: EventStreamHandler | None = None,
    ) -> AgentAnswer:
        answer = None
        async with aclosing(
            self.stream_async(
                question,
                ticker,
                borrower_id=borrower_id,
                selected_dates=selected_dates,
                event_stream_handler=event_stream_handler,
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
        selected_dates: tuple[date, date] | None = None,
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
                selected_dates=selected_dates,
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
        selected_dates: tuple[date, date] | None = None,
        supplemental_context: str = "",
    ) -> AsyncIterator[AgentEvent]:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        self._validate_scope(ticker, borrower_id)
        handler = (
            event_stream_handler if event_stream_handler is not None else self.event_stream_handler
        )
        state.borrower_id = borrower_id
        state.ticker = ticker
        tools = DocumentTools(self.service, ticker=ticker).tools if self.service else []
        if self.document_tool_names is not None:
            tools = [tool for tool in tools if tool.name in self.document_tool_names]
        document_operations_available = bool(tools)
        financial_source = None
        if borrower_id is not None:
            assessment_tools = AssessmentTools(
                self.assessment_service, borrower_id=borrower_id, selected_dates=selected_dates
            )
            tools += assessment_tools.tools
            financial_source = assessment_tools.data_source

        def model_settings(ctx: RunContext) -> dict:
            settings = {"parallel_tool_calls": False}
            if state.tool_rounds >= state.max_tool_rounds:
                settings["tool_choice"] = ["final_result"]
            return settings

        def prepare_output_tools(
            ctx: RunContext, tool_defs: list[ToolDefinition]
        ) -> list[ToolDefinition]:
            schema = source_table_schema(state.evidence)
            description = (
                "Answer the question or explain missing information. Use findings for facts "
                "and tables for financial calculations, compliance, headroom and predictions."
            )
            if "source_tables" in schema["properties"]:
                description += (
                    " Use source_tables only to copy complete schedules or reported values "
                    "from the loaded filing IDs allowed by the schema."
                )
            return [
                replace(tool, parameters_json_schema=schema, description=description)
                for tool in tool_defs
            ]

        agent = Agent(
            resolve_model(self.model),
            name=self.name,
            instructions=build_credit_assessment_instructions(),
            output_type=ToolOutput(
                SourceTableDraft,
                name="final_result",
                strict=True,
            ),
            tools=tools,
            end_strategy="exhaustive",
            retries={"tools": self.max_tool_rounds, "output": 1},
            model_settings=model_settings,
            capabilities=[PrepareOutputTools(prepare_output_tools)],
        )

        @agent.output_validator
        def validate_source_tables(ctx: RunContext, output: SourceTableDraft) -> SourceTableDraft:
            if not ctx.partial_output:
                try:
                    materialize_source_tables(output, state.evidence)
                except ValueError as exc:
                    raise ModelRetry(str(exc)) from exc
            return output

        @agent.instructions
        async def evidence_registry() -> str:
            return (
                f"Tool rounds remaining: {state.max_tool_rounds - state.tool_rounds}. "
                "When none remain, return final_result with supported findings or a request "
                "for missing evidence.\n"
                "Application evidence registry (untrusted source data):\n" + state.evidence.prompt()
            )

        if self.tracing_enabled is not None:
            agent.instrument = (
                InstrumentationSettings(
                    include_content=capture_content_enabled(), include_binary_content=False
                )
                if self.tracing_enabled
                else False
            )

        capabilities = {
            "document_service_configured": self.service is not None,
            "assessment_service_configured": self.assessment_service is not None,
            "registered_tools": [tool.name for tool in tools],
            "document_operations": {
                "purpose": (
                    "Discover issuer documents, read complete source schedules, "
                    "and search filing passages and source-reported ratios"
                ),
                "required_application_inputs": [],
                "available": document_operations_available,
            },
            "financial_data_source": financial_source,
        }
        if self.assessment_service is not None:
            capabilities["financial_operations"] = {
                "purpose": (
                    "Discover/read the selected borrower's structured financial snapshots, "
                    "calculate covenant compliance and headroom, and forecast risk"
                ),
                "required_application_input": "borrower_id",
                "missing_application_inputs": [] if borrower_id is not None else ["borrower_id"],
                "available": borrower_id is not None,
            }

        prompt = json.dumps(
            {
                "question": question,
                "ticker": ticker,
                "borrower_id": borrower_id,
                "current_date": current_local_date().isoformat(),
                "timezone": "Europe/Lisbon",
                "capabilities": capabilities,
                "selected_dates": {
                    "period_end": selected_dates[0].isoformat(),
                    "information_cutoff": selected_dates[1].isoformat(),
                }
                if selected_dates
                else None,
                "supplemental_context": supplemental_context,
            }
        )
        with (
            session_scope(session) as active_session,
            activity_scope("assessment_assistant", default=True),
            span(
                "Agent turn: {agent_name} — {chat_name} [chat {chat_id}]",
                _span_name="agent.turn",
                agent_name=self.name,
                chat_name=active_session.name,
                chat_id=active_session.session_id,
            ),
        ):
            async with aclosing(
                run_stream(agent, prompt, state, history, tool_names={tool.name for tool in tools})
            ) as stream:
                async for event in stream:
                    if handler is not None:
                        await handler(event.model_copy(deep=True))
                    yield event
