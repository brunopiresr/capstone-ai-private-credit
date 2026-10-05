"""Actual SDK response types exercise adaptive tools, RAG, failures, and loop limits."""

import asyncio
import json
from datetime import date
from itertools import count
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APIError, AsyncOpenAI, OpenAI
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseReasoningItem,
)

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
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
        ("get_document_extraction", {"document_id": 3}, "invalid_arguments"),
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
    result = tools.execute("get_document_extraction", {"document_id": "SYN"})
    assert result["data"]["status"] == "stale" and result["data"]["result"] is None
    assert result["sources"] == []


def test_scoped_agent_cannot_process_other_issuer(document_service_factory):
    service = document_service_factory()
    tools = DocumentTools(service, ticker="OTHER")
    result = tools.execute("process_document", {"document_id": "SYN"})
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
    definitions = DocumentTools(document_service_factory()).definitions
    assert len(definitions) == 4
    for tool in definitions:
        schema = tool["parameters"]
        assert tool["strict"] and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert "force" not in schema["properties"] and "client" not in schema["properties"]


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
    outcome = tools.execute(
        "assess_covenants", {"period_end": period, "information_cutoff": period}
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
    ],
)
def test_assessment_arguments_cannot_change_scope_or_configuration(
    agent_assessment_service, arguments, monkeypatch
):
    assess = Mock()
    monkeypatch.setattr(agent_assessment_service, "assess", assess)
    result = AssessmentTools(agent_assessment_service, borrower_id="SYN002").execute(
        "predict_risk", arguments
    )
    assert result["error"] == "invalid_arguments"
    assess.assert_not_called()


def test_financial_tools_do_not_substitute_another_reporting_period(agent_assessment_service):
    tools = AssessmentTools(agent_assessment_service, borrower_id="SYN002")
    result = tools.execute(
        "get_financials", {"period_end": "2025-08-31", "information_cutoff": "2025-08-31"}
    )
    assert result["data"]["current"] is None
    assert len(result["data"]["history"]) == 2
    assert result["data"]["issues"]
    unknown = AssessmentTools(agent_assessment_service, borrower_id="UNKNOWN").execute(
        "predict_risk", ASSESSMENT_DATES
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
    result = tools.execute("get_financials", ASSESSMENT_DATES)
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
    definitions = AssessmentTools(agent_assessment_service, borrower_id="SYN002").definitions
    for tool in definitions:
        schema = tool["parameters"]
        assert tool["strict"] and schema["additionalProperties"] is False
        assert (
            set(schema["required"])
            == set(schema["properties"])
            == {"period_end", "information_cutoff"}
        )
