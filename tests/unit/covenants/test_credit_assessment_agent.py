"""Actual SDK response types exercise adaptive tools, RAG, failures, and loop limits."""

import asyncio
import json
from datetime import date
from itertools import count
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from agents import Agent, OpenAIResponsesModel, RunConfig, Runner
from agents.tool_context import ToolContext
from openai import APIError, AsyncOpenAI, OpenAI
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseReasoningItem,
)

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent, _QuestionHooks
from credit_monitoring.agents.events import AgentEvent, AgentEventCallback
from credit_monitoring.agents.responses_client import ResponsesClientAdapter
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import (
    CalculationRules,
    ExtractionBinding,
    ExtractionCovenantReader,
    SyntheticCovenantReader,
)
from credit_monitoring.domain import (
    CovenantExtraction,
    CovenantTerm,
    SourceEvidence,
    ThresholdScheduleEntry,
)
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials

DATA = Path(__file__).resolve().parents[3] / "data"
ASSESSMENT_DATES = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}

_response_ids = count()


def response(*calls, answer=None, status="completed", refusal=None, reasoning=False):
    response_id = next(_response_ids)
    output = []
    if reasoning:
        output.append(
            ResponseReasoningItem.model_construct(
                id="reasoning",
                type="reasoning",
                summary=[],
                encrypted_content="private-content",
            )
        )
    for index, (name, arguments) in enumerate(calls):
        output.append(
            ResponseFunctionToolCall(
                name=name,
                arguments=arguments if isinstance(arguments, str) else json.dumps(arguments),
                call_id=f"call_{response_id}_{index}_{name}",
                type="function_call",
            )
        )
    if answer is not None or refusal is not None:
        content = (
            [ResponseOutputRefusal(type="refusal", refusal=refusal)]
            if refusal
            else [ResponseOutputText(type="output_text", text=answer, annotations=[], logprobs=[])]
        )
        output.append(
            ResponseOutputMessage(
                type="message",
                id="msg",
                role="assistant",
                status="completed",
                content=content,
            )
        )
    return Response.model_construct(
        id=f"resp_{response_id}", status=status, error=None, output=output
    )


def agent(service, **kwargs):
    client = Mock()
    client.responses.create = AsyncMock()
    return CreditAssessmentAgent(client=client, service=service, **kwargs), client


def test_progress_arrives_before_service_execution_and_keeps_trace(document_service_factory):
    events = []
    states = []

    async def handler(ctx, event):
        events.append(event)
        states.append(ctx.context)
        if event.kind == "tool_call":
            assert not ctx.context.trace
        if event.kind == "tool_result":
            assert ctx.context.trace[-1].outcome == event.outcome

    service = document_service_factory()
    original = service.list_document_extractions

    def list_documents(**kwargs):
        assert events[-1].kind == "tool_call"
        assert events[-1].tool_name == "list_documents"
        return original(**kwargs)

    service.list_document_extractions = list_documents
    monitor, client = agent(service, name="Research")
    client.responses.create.side_effect = [
        response(("list_documents", {"ticker": None}), reasoning=True),
        response(answer="Found the filing."),
    ]
    answer = monitor.ask("Find filings", event_stream_handler=handler)
    assert answer.complete
    assert [event.kind for event in events] == [
        "model_start",
        "tool_call",
        "tool_result",
        "model_start",
        "run_end",
    ]
    assert all(event.agent_name == "Research" for event in events)
    assert all(state is states[0] for state in states)
    assert events[1].arguments == '{"ticker": null}'
    assert events[1].call_id == events[2].call_id == answer.tool_trace[0].call_id
    assert events[2].outcome == answer.tool_trace[0].outcome
    assert "private-content" not in repr(events)


@pytest.mark.parametrize(
    "name,arguments,error",
    [
        ("unknown", {}, "unknown_tool"),
        ("get_document_extraction", "{broken json", "invalid_arguments"),
        ("search_evidence", {"query": "leverage", "ticker": "OTHER"}, "service_error"),
    ],
)
def test_progress_reports_tool_errors_and_continues(
    document_service_factory, name, arguments, error
):
    events = []

    async def handler(ctx, event):
        events.append(event)

    monitor, client = agent(document_service_factory(), event_stream_handler=handler)
    client.responses.create.side_effect = [
        response((name, arguments)),
        response(answer="Evidence unavailable."),
    ]
    answer = asyncio.run(monitor.ask_async("Find evidence", ticker="SYN"))
    assert answer.complete
    assert [event.kind for event in events] == [
        "model_start",
        "tool_call",
        "tool_result",
        "model_start",
        "run_end",
    ]
    assert events[2].outcome["error"] == error
    assert events[2].outcome == answer.tool_trace[0].outcome


def test_progress_reports_round_limit_without_excess_tool_call(document_service_factory):
    events = []

    async def handler(ctx, event):
        events.append(event)

    monitor, client = agent(
        document_service_factory(), max_tool_rounds=1, event_stream_handler=handler
    )
    client.responses.create.side_effect = lambda **kwargs: response(("list_documents", {}))
    answer = monitor.ask("Find filings")
    assert answer.error == "tool_round_limit"
    assert [event.kind for event in events] == [
        "model_start",
        "tool_call",
        "tool_result",
        "model_start",
        "run_end",
    ]
    assert events[-1].error == answer.error
    assert len(answer.tool_trace) == 1


@pytest.mark.parametrize(
    "model_response,error",
    [
        (response(status="incomplete"), "model_incomplete"),
        (response(refusal="Cannot answer"), "model_refusal"),
        (response(), "empty_response"),
        (
            APIError(
                "Offline", request=httpx.Request("POST", "https://example.invalid"), body=None
            ),
            "model_error",
        ),
    ],
)
def test_progress_reports_model_failure(document_service_factory, model_response, error):
    events = []

    async def handler(ctx, event):
        events.append(event)

    monitor, client = agent(document_service_factory())
    client.responses.create.side_effect = [model_response]
    answer = monitor.ask("Find filings", event_stream_handler=handler)
    assert answer.error == error
    assert [event.kind for event in events] == ["model_start", "run_end"]
    assert events[-1].error == error


def test_handler_override_is_per_question_and_silent_default(document_service_factory, capsys):
    default = AsyncMock()
    override = AsyncMock()
    monitor, client = agent(document_service_factory(), event_stream_handler=default)
    client.responses.create.side_effect = [response(answer="One"), response(answer="Two")]
    monitor.ask("One", event_stream_handler=override)
    default.assert_not_awaited()
    monitor.ask("Two")
    assert default.await_count == override.await_count == 2
    assert (
        default.call_args_list[0].args[0].context is not override.call_args_list[0].args[0].context
    )
    assert capsys.readouterr().out == ""


def test_callback_prints_nested_streams_and_error_status(capsys):
    ctx = Mock()
    callback = AgentEventCallback(Mock(name="unused"))
    callback.agent.name = "Notebook agent"

    async def nested():
        yield AgentEvent("tool_call", "SDK name", tool_name="list_documents", arguments="{}")
        yield AgentEvent(
            "tool_result", "SDK name", tool_name="list_documents", outcome={"ok": True}
        )
        yield AgentEvent(
            "tool_result",
            "SDK name",
            tool_name="missing",
            outcome={
                "ok": False,
                "error": "unknown_tool",
                "message": "private payload",
            },
        )

    async def stream():
        yield AgentEvent("model_start", "SDK name")
        yield nested()
        yield AgentEvent("run_end", "SDK name", error="tool_round_limit")

    asyncio.run(callback(ctx, stream()))
    assert capsys.readouterr().out.splitlines() == [
        "MODEL REQUEST (Notebook agent)",
        "TOOL CALL (Notebook agent): list_documents({})",
        "TOOL RESULT (Notebook agent): list_documents — ok",
        "TOOL RESULT (Notebook agent): missing — error: unknown_tool",
        "AGENT FINISHED (Notebook agent): incomplete: tool_round_limit",
    ]


def test_callback_uses_event_agent_name_when_unbound(document_service_factory, capsys):
    monitor, client = agent(document_service_factory(), event_stream_handler=AgentEventCallback())
    client.responses.create.return_value = response(answer="Done")
    assert monitor.ask("Find filings").complete
    assert capsys.readouterr().out.splitlines() == [
        "MODEL REQUEST (Credit assessment agent)",
        "AGENT FINISHED (Credit assessment agent): complete",
    ]


def invoke_tool(container, name, arguments):
    """Invoke an actual SDK function tool without a model or service dispatcher."""
    tool = next(tool for tool in container.tools if tool.name == name)
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    context = ToolContext(
        context=AgentRunState(max_tool_rounds=6),
        tool_name=name,
        tool_call_id="direct_test_call",
        tool_arguments=raw,
    )
    return json.loads(asyncio.run(tool.on_invoke_tool(context, raw)))


def test_document_discovery_processing_cache_read_and_rag_loop(
    document_service_factory,
    sdk_response,
):
    service = document_service_factory()
    service.client.responses.parse.return_value = sdk_response(CovenantExtraction())
    monitor, client = agent(service)
    client.responses.create.side_effect = [
        response(("list_documents", {"ticker": None}), reasoning=True),
        response(("get_document_extraction", {"document_id": "SYN"})),
        response(("process_document", {"document_id": "SYN"})),
        response(("process_document", {"document_id": "SYN"})),
        response(("search_evidence", {"query": "maximum leverage", "ticker": None})),
        response(answer="The filing states 4.00 to 1.00. [SYN] Synthetic Issuer, Amendment."),
    ]
    answer = monitor.ask("Show the schedule and supporting filing text.", ticker="SYN")
    assert answer.complete and len(answer.tool_trace) == 5
    assert answer.tool_trace[0].outcome["data"][0]["status"] == "missing"
    assert answer.tool_trace[1].outcome["data"]["result"] is None
    assert not answer.tool_trace[2].outcome["data"]["cache_hit"]
    assert answer.tool_trace[3].outcome["data"]["cache_hit"]
    service.client.responses.parse.assert_called_once()
    assert [s.document_id for s in answer.sources] == ["SYN"]
    assert "private-content" not in answer.model_dump_json()
    second_input = client.responses.create.call_args_list[1].kwargs["input"]
    assert any(item.get("type") == "function_call_output" for item in second_input)
    final_input = client.responses.create.call_args_list[-1].kwargs["input"]
    results = [
        json.loads(i["output"]) for i in final_input if i.get("type") == "function_call_output"
    ]
    assert "Maximum leverage" in results[-1]["data"][0]["content"]


@pytest.mark.parametrize(
    "name,arguments,error",
    [
        ("unknown", {}, "unknown_tool"),
        ("get_document_extraction", "{broken json", "invalid_arguments"),
        ("get_document_extraction", "[]", "invalid_arguments"),
        ("process_document", {"document_id": "SYN", "force": True}, "invalid_arguments"),
        ("get_document_extraction", {"document_id": ""}, "invalid_arguments"),
        ("get_document_extraction", {"document_id": 3}, "invalid_arguments"),
        ("list_documents", {"ticker": 3}, "invalid_arguments"),
        ("search_evidence", {"query": ""}, "invalid_arguments"),
        ("search_evidence", {"query": "leverage", "ctx": {}}, "invalid_arguments"),
        ("get_document_extraction", {"document_id": "UNKNOWN"}, "service_error"),
        ("search_evidence", {"query": "leverage", "ticker": "OTHER"}, "service_error"),
    ],
)
def test_dispatch_errors_are_results_for_next_agent_round(
    name,
    arguments,
    error,
    document_service_factory,
):
    monitor, client = agent(document_service_factory())
    client.responses.create.side_effect = [
        response((name, arguments)),
        response(answer="The requested evidence is unavailable."),
    ]
    result = monitor.ask("Question", ticker="SYN")
    assert result.tool_trace[0].outcome["error"] == error
    history = client.responses.create.call_args_list[1].kwargs["input"]
    assert json.loads(history[-1]["output"])["error"] == error


def test_stale_result_is_visible_and_cannot_supply_old_facts(
    document_service_factory, sdk_response
):
    service = document_service_factory()
    service.client.responses.parse.return_value = sdk_response(CovenantExtraction())
    service.process_document("SYN")
    service.model = "changed-model"
    tools = DocumentTools(service)
    result = invoke_tool(tools, "get_document_extraction", {"document_id": "SYN"})
    assert result["data"]["status"] == "stale" and result["data"]["result"] is None
    assert result["sources"] == []


def test_scoped_agent_cannot_process_other_issuer(document_service_factory):
    service = document_service_factory()
    tools = DocumentTools(service, ticker="OTHER")
    result = invoke_tool(tools, "process_document", {"document_id": "SYN"})
    assert result["error"] == "service_error"
    service.client.responses.parse.assert_not_called()


def test_six_tool_round_limit_does_not_execute_seventh_call(document_service_factory):
    monitor, client = agent(document_service_factory())
    client.responses.create.side_effect = lambda **kwargs: response(
        ("list_documents", {"ticker": None})
    )
    result = monitor.ask("Question")
    assert not result.complete and result.error == "tool_round_limit"
    assert len(result.tool_trace) == 6 and client.responses.create.call_count == 7


@pytest.mark.parametrize(
    "sdk_result,error",
    [
        (response(status="incomplete"), "model_incomplete"),
        (response(status="failed"), "model_error"),
        (response(refusal="Cannot answer"), "model_refusal"),
        (response(), "empty_response"),
    ],
)
def test_model_failures_are_explicit(sdk_result, error, document_service_factory):
    monitor, client = agent(document_service_factory())
    client.responses.create.return_value = sdk_result
    result = monitor.ask("Question")
    assert not result.complete and result.error == error


def test_api_failure_retains_executed_trace(document_service_factory):
    monitor, client = agent(document_service_factory())
    client.responses.create.side_effect = [
        response(("list_documents", {"ticker": None})),
        APIError(
            "Offline test failure",
            request=httpx.Request("POST", "https://example.invalid"),
            body=None,
        ),
    ]
    result = monitor.ask("Question")
    assert result.error == "model_error" and len(result.tool_trace) == 1


def test_tool_schemas_are_strict_and_configuration_is_not_exposed(document_service_factory):
    definitions = DocumentTools(document_service_factory()).tools
    assert len(definitions) == 4
    for tool in definitions:
        schema = tool.params_json_schema
        assert tool.strict_json_schema and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert "force" not in schema["properties"] and "client" not in schema["properties"]
        assert "self" not in schema["properties"] and "ctx" not in schema["properties"]


def test_sdk_uses_tool_and_parameter_docstrings(document_service_factory, agent_assessment_service):
    tools = (
        DocumentTools(document_service_factory()).tools
        + AssessmentTools(agent_assessment_service, borrower_id="SYN002").tools
    )
    for tool in tools:
        assert tool.description
        assert "Args:" not in tool.description
        for parameter in tool.params_json_schema["properties"].values():
            assert parameter["description"]
    descriptions = {tool.name: tool.description for tool in tools}
    assert "use process_document" in descriptions["get_document_extraction"]
    assert "does not invoke ML" in descriptions["assess_covenants"]
    assert "stub supplies no forecast" in descriptions["predict_risk"]


def test_tool_classes_are_reusable_by_independent_sdk_agents():
    first_service, second_service = Mock(), Mock()
    first_service.search_evidence.return_value = [
        {"document_id": "FIRST", "citation": "First filing", "content": "First evidence"}
    ]
    second_service.search_evidence.return_value = [
        {"document_id": "SECOND", "citation": "Second filing", "content": "Second evidence"}
    ]
    first_tools = DocumentTools(first_service, ticker="FIRST")
    second_tools = DocumentTools(second_service, ticker="SECOND")

    async def run(container):
        client = Mock()
        client.responses.create = AsyncMock(
            side_effect=[
                response(("search_evidence", {"query": "leverage", "ticker": None})),
                response(answer="Evidence retrieved."),
            ]
        )
        sdk_agent = Agent[AgentRunState](
            name="Reusable research agent",
            model=OpenAIResponsesModel(
                model="gpt-4o-mini", openai_client=ResponsesClientAdapter(client)
            ),
            tools=container.tools,
        )
        state = AgentRunState(max_tool_rounds=1)
        await Runner.run(
            sdk_agent,
            "Find leverage evidence.",
            context=state,
            hooks=_QuestionHooks(),
            run_config=RunConfig(tracing_disabled=True),
        )
        return state

    async def run_both():
        return await asyncio.gather(run(first_tools), run(second_tools))

    first, second = asyncio.run(run_both())
    first_service.search_evidence.assert_called_once_with(query="leverage", ticker="FIRST")
    second_service.search_evidence.assert_called_once_with(query="leverage", ticker="SECOND")
    assert [source.document_id for source in first.sources.values()] == ["FIRST"]
    assert [source.document_id for source in second.sources.values()] == ["SECOND"]
    assert first.trace[0].outcome["data"][0]["content"] == "First evidence"
    assert second.trace[0].outcome["data"][0]["content"] == "Second evidence"


@pytest.mark.parametrize("async_client", [False, True])
def test_installed_sdk_serializes_tool_call_continuation(document_service_factory, async_client):
    captured = []
    count = 0

    def respond(request):
        nonlocal count
        captured.append(json.loads(request.content))
        count += 1
        item = (
            response(("search_evidence", {"query": "leverage", "ticker": "SYN"}))
            if count == 1
            else response(answer="See SYN, the cited amendment.")
        )
        data = item.model_dump(exclude_none=True)
        data.update(
            {
                "object": "response",
                "created_at": 0,
                "model": "gpt-4o-mini",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "temperature": 1,
                "top_p": 1,
                "text": {"format": {"type": "text"}},
                "truncation": "disabled",
                "usage": None,
            }
        )
        return httpx.Response(200, json=data)

    service = document_service_factory()
    if async_client:

        async def ask():
            async with AsyncOpenAI(
                api_key="offline-test-key",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            ) as client:
                return await CreditAssessmentAgent(client=client, service=service).ask_async(
                    "Question", "SYN"
                )

        result = asyncio.run(ask())
    else:
        with OpenAI(
            api_key="offline-test-key",
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        ) as client:
            result = CreditAssessmentAgent(client=client, service=service).ask("Question", "SYN")
    assert result.complete and len(result.tool_trace) == 1
    assert captured[0]["tools"][0]["type"] == "function"
    assert captured[1]["input"][-1]["type"] == "function_call_output"
    assert "Maximum leverage" in captured[1]["input"][-1]["output"]


@pytest.mark.parametrize("limit", [1, 6])
def test_last_permitted_model_turn_can_answer(document_service_factory, limit):
    monitor, client = agent(document_service_factory(), max_tool_rounds=limit)
    client.responses.create.side_effect = [
        *(response(("list_documents", {"ticker": None})) for _ in range(limit)),
        response(answer="The available documents are listed."),
    ]
    result = monitor.ask("List available documents.")
    assert result.complete and len(result.tool_trace) == limit
    assert client.responses.create.call_count == limit + 1


def test_multiple_calls_use_one_round_and_execute_in_order(document_service_factory, sdk_response):
    service = document_service_factory()
    monitor, client = agent(service, max_tool_rounds=1)
    client.responses.create.side_effect = [
        response(
            ("get_document_extraction", {"document_id": "SYN"}),
            ("process_document", {"document_id": "SYN"}),
            ("get_document_extraction", {"document_id": "SYN"}),
        ),
        response(answer="The document is now processed."),
    ]
    service.client.responses.parse.return_value = sdk_response(CovenantExtraction())
    result = monitor.ask("Read the stored document, process it, then read it again.")
    assert result.complete and len(result.tool_trace) == 3
    assert [item.outcome["data"]["status"] for item in result.tool_trace] == [
        "missing",
        "complete",
        "complete",
    ]
    service.client.responses.parse.assert_called_once()


@pytest.mark.parametrize("status", ["incomplete", "failed", "in_progress"])
def test_non_completed_output_never_executes_tools(document_service_factory, status):
    service = document_service_factory()
    monitor, client = agent(service)
    client.responses.create.return_value = response(
        ("process_document", {"document_id": "SYN"}), status=status
    )
    result = monitor.ask("Process SYN.")
    assert not result.complete and result.tool_trace == []
    assert result.error == ("model_incomplete" if status == "incomplete" else "model_error")
    service.client.responses.parse.assert_not_called()


def test_concurrent_read_questions_keep_scope_and_sources_separate(document_service_factory):
    monitor, client = agent(document_service_factory())

    async def respond(**kwargs):
        payload = json.loads(kwargs["input"][0]["content"])
        if any(item.get("type") == "function_call_output" for item in kwargs["input"]):
            return response(answer=f"Evidence for {payload['ticker']}.")
        return response(("search_evidence", {"query": "maximum leverage", "ticker": None}))

    client.responses.create.side_effect = respond

    async def ask_both():
        return await asyncio.gather(
            monitor.ask_async("Find filing evidence.", ticker="SYN"),
            monitor.ask_async("Find filing evidence.", ticker="OTHER"),
        )

    syn, other = asyncio.run(ask_both())
    assert syn.complete and other.complete
    assert [source.document_id for source in syn.sources] == ["SYN"]
    assert other.sources == []
    assert len(syn.tool_trace) == len(other.tool_trace) == 1
    assert syn.answer == "Evidence for SYN." and other.answer == "Evidence for OTHER."


def test_sync_entry_point_in_running_loop_explains_async_usage(document_service_factory):
    monitor, client = agent(document_service_factory())

    async def ask():
        with pytest.raises(RuntimeError, match="await agent.ask_async"):
            monitor.ask("Question")

    asyncio.run(ask())
    client.responses.create.assert_not_called()


@pytest.fixture
def agent_assessment_service(tmp_path):
    financial_db = tmp_path / "financials.sqlite3"
    load_financials(DATA / "synthetic_quarterly_financials.csv", financial_db)
    return AssessmentService(
        financial_repository=FinancialRepository(financial_db),
        covenant_reader=SyntheticCovenantReader(DATA / "synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(analytics_database=tmp_path / "analytics.sqlite3"),
    )


def test_agent_calls_real_financial_calculation_and_prediction_services(
    document_service_factory, agent_assessment_service
):
    assessor, client = agent(
        document_service_factory(), assessment_service=agent_assessment_service
    )
    client.responses.create.side_effect = [
        response(("get_financials", ASSESSMENT_DATES)),
        response(("assess_covenants", ASSESSMENT_DATES)),
        response(("predict_risk", ASSESSMENT_DATES)),
        response(answer="Current covenant compliance is established; the stub has no forecast."),
    ]
    answer = assessor.ask(
        "Assess and forecast SYN002 for the supplied dates.", borrower_id="SYN002"
    )
    assert answer.complete and len(answer.tool_trace) == 3
    financials, calculated, predicted = [item.outcome["data"] for item in answer.tool_trace]
    assert financials["current"]["metrics"]["reported_ebitda"] == 26
    assert len(financials["history"]) == 2
    assert calculated["results"][0]["actual_value"] == pytest.approx(135 / 26)
    assert calculated["results"][0]["headroom"] == pytest.approx(5.5 - 135 / 26)
    assert calculated["results"][0]["compliance_status"] == "compliant"
    assert calculated["ml_status"] == "disabled" and calculated["prediction"] is None
    assert predicted["verification"]["is_valid"]
    assert predicted["ml_status"] == "stub"
    assert predicted["prediction"]["breach_probability"] is None
    assert predicted["prediction"]["snapshot_id"] == predicted["feature_snapshot"]["snapshot_id"]
    assert (
        len(
            agent_assessment_service.result_repository.get_history(
                "SYN002",
                period_end=date(2025, 9, 30),
                information_cutoff=date(2025, 9, 30),
                assessment_run_id=predicted["assessment_run_id"],
            )
        )
        == 3
    )
    assert "Subsequent breach" not in answer.model_dump_json()
    assert '"notes"' not in answer.model_dump_json()
    assert "expected_metric" not in answer.model_dump_json()
    request = client.responses.create.call_args_list[0].kwargs
    assert {tool["name"] for tool in request["tools"]} >= {
        "get_financials",
        "assess_covenants",
        "predict_risk",
        "search_evidence",
    }
    last_input = client.responses.create.call_args_list[-1].kwargs["input"]
    outputs = [
        json.loads(item["output"])
        for item in last_input
        if item.get("type") == "function_call_output"
    ]
    assert outputs[-1]["data"]["ml_status"] == "stub"


@pytest.mark.parametrize(
    "borrower,period,status,threshold",
    [
        ("SYN004", "2025-06-30", "incomplete", 4.75),
        ("SYN004", "2025-09-30", "compliant", 5.5),
        ("SYN005", "2025-09-30", "waived", 4.5),
        ("SYN010", "2025-09-30", "incomplete", 1.15),
    ],
)
def test_tools_preserve_contractual_applicability_and_missing_inputs(
    agent_assessment_service, borrower, period, status, threshold
):
    tools = AssessmentTools(agent_assessment_service, borrower_id=borrower)
    agent_assessment_service.settings.ml_enabled = True
    outcome = invoke_tool(
        tools, "assess_covenants", {"period_end": period, "information_cutoff": period}
    )
    assert outcome["ok"]
    assert outcome["data"]["results"][0]["compliance_status"] == status
    assert outcome["data"]["results"][0]["threshold"] == threshold
    assert outcome["data"]["ml_status"] == "disabled"
    if status in ("waived", "incomplete"):
        assert outcome["data"]["results"][0]["headroom"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"period_end": "2025-02-30", "information_cutoff": "2025-09-30"},
        {"period_end": "2025-09-30", "information_cutoff": "2025-06-30"},
        {"period_end": "2025-09-30"},
        {**ASSESSMENT_DATES, "borrower_id": "OTHER"},
        {**ASSESSMENT_DATES, "formula": "total_debt / ebitda"},
        {**ASSESSMENT_DATES, "model_artifact": "/tmp/other"},
        {**ASSESSMENT_DATES, "ml_enabled": True},
        {**ASSESSMENT_DATES, "period_end": 20250930},
        {**ASSESSMENT_DATES, "period_end": "2025-9-30"},
        {**ASSESSMENT_DATES, "information_cutoff": 20250930},
        {**ASSESSMENT_DATES, "ctx": {}},
    ],
)
def test_assessment_arguments_cannot_change_scope_or_configuration(
    agent_assessment_service, arguments, monkeypatch
):
    assess = Mock()
    monkeypatch.setattr(agent_assessment_service, "assess", assess)
    result = invoke_tool(
        AssessmentTools(agent_assessment_service, borrower_id="SYN002"), "predict_risk", arguments
    )
    assert result["error"] == "invalid_arguments"
    assess.assert_not_called()


def test_financial_tools_do_not_substitute_another_reporting_period(agent_assessment_service):
    tools = AssessmentTools(agent_assessment_service, borrower_id="SYN002")
    result = invoke_tool(
        tools, "get_financials", {"period_end": "2025-08-31", "information_cutoff": "2025-08-31"}
    )
    assert result["data"]["current"] is None
    assert len(result["data"]["history"]) == 2
    assert result["data"]["issues"]
    unknown = invoke_tool(
        AssessmentTools(agent_assessment_service, borrower_id="UNKNOWN"),
        "predict_risk",
        ASSESSMENT_DATES,
    )
    assert unknown["data"]["results"] == []
    assert unknown["data"]["ml_status"] == "unavailable"
    assert unknown["data"]["prediction"] is None


def test_financial_tools_respect_known_availability(agent_assessment_service, monkeypatch):
    row = agent_assessment_service.financial_repository.get_quarter("SYN002", "2025-09-30")
    row["available_at"] = "2025-10-15"
    monkeypatch.setattr(
        agent_assessment_service.financial_repository, "get_history", Mock(return_value=[row])
    )
    tools = AssessmentTools(agent_assessment_service, borrower_id="SYN002")
    result = invoke_tool(tools, "get_financials", ASSESSMENT_DATES)
    assert result["data"]["current"] is None and result["data"]["history"] == []
    assert any("exceed the cutoff" in issue for issue in result["data"]["issues"])


def test_prediction_model_failure_returns_calculations_to_agent(
    document_service_factory, agent_assessment_service, tmp_path
):
    agent_assessment_service.settings.risk_model = RiskModelConfig(
        type="logistic_regression", artifact_path=tmp_path / "missing-model"
    )
    assessor, client = agent(
        document_service_factory(), assessment_service=agent_assessment_service
    )
    client.responses.create.side_effect = [
        response(("predict_risk", ASSESSMENT_DATES)),
        response(answer="Current compliance is available; the prediction model failed to load."),
    ]
    result = assessor.ask("Assess and predict risk.", borrower_id="SYN002")
    assert result.complete
    data = result.tool_trace[0].outcome["data"]
    assert data["ml_status"] == "failed"
    assert data["results"][0]["compliance_status"] == "compliant"
    assert data["prediction"]["breach_probability"] is None
    assert data["verification"]["is_valid"]


def test_assessment_tools_require_application_configuration_and_borrower_scope(
    document_service_factory, agent_assessment_service
):
    assessor, client = agent(document_service_factory())
    with pytest.raises(ValueError, match="assessment_service"):
        assessor.ask("Assess", borrower_id="SYN002")
    client.responses.create.assert_not_called()
    assessor, client = agent(
        document_service_factory(), assessment_service=agent_assessment_service
    )
    with pytest.raises(ValueError, match="explicit borrower"):
        assessor.ask("Assess", borrower_id=" ")
    client.responses.create.side_effect = [
        response(("predict_risk", ASSESSMENT_DATES)),
        response(answer="Provide an explicit borrower scope to enable assessment tools."),
    ]
    result = assessor.ask("Assess SYN002.")
    assert result.tool_trace[0].outcome["error"] == "unknown_tool"
    tool_names = {
        tool["name"] for tool in client.responses.create.call_args_list[0].kwargs["tools"]
    }
    assert "predict_risk" not in tool_names


def test_concurrent_assessments_keep_borrower_scopes_separate(
    document_service_factory, agent_assessment_service
):
    assessor, client = agent(
        document_service_factory(), assessment_service=agent_assessment_service
    )

    async def respond(**kwargs):
        payload = json.loads(kwargs["input"][0]["content"])
        if any(item.get("type") == "function_call_output" for item in kwargs["input"]):
            return response(answer=f"Assessment for {payload['borrower_id']}.")
        return response(("assess_covenants", ASSESSMENT_DATES))

    client.responses.create.side_effect = respond

    async def ask_both():
        return await asyncio.gather(
            assessor.ask_async("Assess", borrower_id="SYN002"),
            assessor.ask_async("Assess", borrower_id="SYN004"),
        )

    first, second = asyncio.run(ask_both())
    assert first.tool_trace[0].outcome["data"]["borrower_id"] == "SYN002"
    assert second.tool_trace[0].outcome["data"]["borrower_id"] == "SYN004"
    assert first.answer == "Assessment for SYN002."
    assert second.answer == "Assessment for SYN004."


def test_round_budget_stops_prediction_before_it_executes(
    document_service_factory, agent_assessment_service
):
    assessor, client = agent(
        document_service_factory(), assessment_service=agent_assessment_service, max_tool_rounds=1
    )
    client.responses.create.side_effect = [
        response(("get_financials", ASSESSMENT_DATES)),
        response(("predict_risk", ASSESSMENT_DATES)),
    ]
    result = assessor.ask("Predict risk", borrower_id="SYN002")
    assert result.error == "tool_round_limit" and len(result.tool_trace) == 1
    assert (
        agent_assessment_service.result_repository.get_history(
            "SYN002", period_end=date(2025, 9, 30), information_cutoff=date(2025, 9, 30)
        )
        == []
    )


def test_prediction_tool_loads_actual_trained_baseline(
    document_service_factory, agent_assessment_service, tmp_path
):
    pytest.importorskip("sklearn")
    from credit_monitoring.ml.synthetic_dataset import generate_dataset
    from credit_monitoring.ml.training import train_model

    dataset, artifact = tmp_path / "training", tmp_path / "model"
    generate_dataset(DATA, dataset, borrowers_per_scenario=5)
    train_model(dataset, artifact)
    agent_assessment_service.settings.risk_model = RiskModelConfig(
        type="logistic_regression", artifact_path=artifact
    )
    assessor, client = agent(
        document_service_factory(), assessment_service=agent_assessment_service
    )
    client.responses.create.side_effect = [
        response(("predict_risk", ASSESSMENT_DATES)),
        response(answer="The synthetic baseline supplies a next-quarter prediction."),
    ]
    answer = assessor.ask("Predict next-quarter breach risk.", borrower_id="SYN002")
    data = answer.tool_trace[0].outcome["data"]
    assert answer.complete and data["ml_status"] == "complete"
    prediction = data["prediction"]
    assert 0 <= prediction["breach_probability"] <= 1
    assert prediction["model_name"] == "logistic_regression"
    assert prediction["model_artifact_hash"]
    assert prediction["snapshot_id"] == data["feature_snapshot"]["snapshot_id"]
    assert data["results"][0]["compliance_status"] == "compliant"
    stored = agent_assessment_service.prediction_repository.get(prediction["prediction_id"])
    assert stored.breach_probability == prediction["breach_probability"]


def test_agent_processes_document_then_assesses_bound_formula_with_sources(
    document_service_factory, agent_assessment_service, sdk_response
):
    text = "# Agreement\n\nMaximum leverage 5.50 to 1.00 for September 30, 2025.\n"
    document_service = document_service_factory(text)
    citation = document_service.get_document_extraction("SYN").citation
    evidence = SourceEvidence(document_id="SYN", citation=citation, evidence_quote=text)
    document_service.client.responses.parse.return_value = sdk_response(
        CovenantExtraction(
            covenants=[
                CovenantTerm(
                    covenant_name="Maximum leverage",
                    covenant_type="leverage",
                    metric="Leverage ratio",
                    operator="<=",
                    operator_quote="Maximum",
                    threshold_direction="maximum",
                    evidence=evidence,
                    threshold_schedule=[
                        ThresholdScheduleEntry(
                            threshold="5.50 to 1.00",
                            period_end_dates=[date(2025, 9, 30)],
                            evidence=evidence,
                        )
                    ],
                )
            ]
        )
    )
    agent_assessment_service.covenant_reader = ExtractionCovenantReader(
        document_service,
        [
            ExtractionBinding(
                borrower_id="SYN002",
                agreement_id="agreement-1",
                covenant_id="agreement-1:leverage",
                covenant_name="Maximum leverage",
                document_id="SYN",
                calculation_rules=CalculationRules(
                    formula="net_leverage",
                    cash_netting_cap=20,
                    measurement_basis="Explicitly configured contractual basis",
                ),
            )
        ],
    )
    assessor, client = agent(document_service, assessment_service=agent_assessment_service)
    client.responses.create.side_effect = [
        response(("process_document", {"document_id": "SYN"})),
        response(("assess_covenants", ASSESSMENT_DATES)),
        response(answer=f"The calculated covenant is compliant. [SYN] {citation}"),
    ]
    answer = assessor.ask(
        "Process and assess the configured agreement.", ticker="SYN", borrower_id="SYN002"
    )
    assert answer.complete
    result = answer.tool_trace[-1].outcome["data"]["results"][0]
    assert result["actual_value"] == pytest.approx(135 / 26)
    assert result["headroom"] == pytest.approx(5.5 - 135 / 26)
    assert result["financial_inputs"]["result_basis"] == "calculated"
    assert result["compliance_status"] == "compliant"
    assert answer.tool_trace[-1].outcome["sources"]
    assert [(source.document_id, source.citation) for source in answer.sources] == [
        ("SYN", citation)
    ]
    document_service.client.responses.parse.assert_called_once()


def test_assessment_schemas_expose_dates_only(agent_assessment_service):
    definitions = AssessmentTools(agent_assessment_service, borrower_id="SYN002").tools
    for tool in definitions:
        schema = tool.params_json_schema
        assert tool.strict_json_schema and schema["additionalProperties"] is False
        assert (
            set(schema["required"])
            == set(schema["properties"])
            == {"period_end", "information_cutoff"}
        )
