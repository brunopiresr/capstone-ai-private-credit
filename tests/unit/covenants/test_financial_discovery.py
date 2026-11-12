"""Financial metadata discovery and context work without a prescribed workflow."""

import hashlib
import json
from datetime import date
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.prompts.credit_assessment import build_credit_assessment_instructions
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.application.bootstrap import create_assessment_service
from credit_monitoring.application.borrower_workflow import SavedAssessmentChat
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.domain.assessment import FinancialPeriod
from credit_monitoring.domain.tool_results import FinancialPeriodCatalog
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.paths import APP_SYNTHETIC_DIR, MODELS_DIR


@pytest.fixture
def service(tmp_path):
    database = tmp_path / "financials.sqlite3"
    load_financials(APP_SYNTHETIC_DIR / "synthetic_quarterly_financials.csv", database)
    return create_assessment_service(
        financial_repository=FinancialRepository(database),
        covenant_reader=SyntheticCovenantReader(APP_SYNTHETIC_DIR / "synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(analytics_database=tmp_path / "analytics.sqlite3"),
    )


@pytest.mark.parametrize("risk_model", ["stub", "logistic_regression"])
def test_financial_assessment_and_prediction_use_financial_output_schema(service, risk_model):
    if risk_model == "logistic_regression":
        pytest.importorskip("sklearn")
    service.settings.risk_model = RiskModelConfig(
        type=risk_model,
        artifact_path=MODELS_DIR / "logistic_regression/v1" if risk_model != "stub" else None,
    )
    documents = Mock()

    def answer_from_financials(*, messages, info):
        assert "source_tables" not in info.output_tools[0].parameters_json_schema["properties"]
        return model_response(answer="Current compliance and forecast are available.")

    dates = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_financials", dates)),
        model_response(("assess_covenants", dates)),
        model_response(("predict_risk", dates)),
        answer_from_financials,
    ]
    answer = CreditAssessmentAgent(service=documents, assessment_service=service, model=model).ask(
        "Read financials, assess compliance and headroom, and request a next-quarter prediction.",
        borrower_id="SYN002",
        selected_dates=(date(2025, 9, 30), date(2025, 9, 30)),
    )
    assert answer.complete and model.respond.call_count == 4
    assert [step.name for step in answer.tool_trace] == [
        "get_financials",
        "assess_covenants",
        "predict_risk",
    ]
    prediction = answer.tool_trace[-1].outcome
    assert prediction.ml_status == ("stub" if risk_model == "stub" else "complete")
    assert prediction.period_end == prediction.information_cutoff == date(2025, 9, 30)
    assert documents.mock_calls == []


def test_discovery_is_read_only_and_excludes_metrics_and_annotations(service):
    database = service.financial_repository.database_path
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    service.assess = Mock(side_effect=AssertionError("Discovery must not calculate"))
    result = AssessmentTools(service, borrower_id="SYN002").list_financial_periods()
    assert result.borrower_id == "SYN002" and result.source == "financial_repository"
    assert result.source_assessment_run_id is None
    assert [p.period_end for p in result.periods] == [
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
        date(2025, 12, 31),
    ]
    assert all(p.available_at is None for p in result.periods)
    assert all(set(p) == {"period_end", "available_at"} for p in result.model_dump()["periods"])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    service.assess.assert_not_called()


def test_discovery_preserves_known_and_unknown_availability_and_sorts():
    service = Mock()
    service.financial_repository.get_period_history.return_value = [
        FinancialPeriod(
            borrower_id="SYN002",
            period_end=date(2025, 9, 30),
            available_at=date(2025, 11, 15),
            metrics={"reported_ebitda": 26},
        ),
        FinancialPeriod(borrower_id="SYN002", period_end=date(2025, 6, 30)),
    ]
    result = AssessmentTools(service, borrower_id="SYN002").list_financial_periods()
    assert result.periods[0].available_at is None
    assert result.periods[1].available_at == date(2025, 11, 15)
    service.financial_repository.get_period_history.assert_called_once_with("SYN002")


def test_unknown_borrower_returns_an_empty_catalog(service):
    assert AssessmentTools(service, borrower_id="SYN999").list_financial_periods().periods == []


def test_saved_snapshot_discovery_does_not_read_the_live_repository(service):
    snapshot = service.assess("SYN002", date(2025, 6, 30), date(2025, 6, 30), ml_enabled=False)
    live = AssessmentTools(service, borrower_id="SYN002").list_financial_periods()
    workflow = Mock()
    saved = SavedAssessmentChat(workflow, snapshot)
    tools = AssessmentTools(saved, borrower_id="SYN002")
    catalog = tools.list_financial_periods()
    assert max(p.period_end for p in live.periods) == date(2025, 12, 31)
    assert max(p.period_end for p in catalog.periods) == date(2025, 6, 30)
    assert (
        catalog.source == "saved_assessment"
        and catalog.source_assessment_run_id == snapshot.assessment_run_id
    )
    assert tools.data_source["information_cutoff"] == "2025-06-30"
    assert workflow.mock_calls == []


def test_graph_retains_discovery_in_trace_and_history(service, monkeypatch):
    monkeypatch.setattr(
        "credit_monitoring.agents.credit_assessment.current_local_date", lambda: date(2026, 11, 11)
    )
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("list_financial_periods", {})),
        model_response(
            ("assess_covenants", {"period_end": "2025-12-31", "information_cutoff": "2026-11-11"})
        ),
        model_response(answer="Latest stored period assessed using today's cutoff."),
        model_response(answer="The stored source has unknown availability."),
    ]
    chat = CreditAssessmentAgent(assessment_service=service, model=model).start_conversation(
        borrower_id="SYN002"
    )
    answer = chat.ask("Use the latest available figures.")
    assert answer.complete
    assert isinstance(answer.tool_trace[0].outcome, FinancialPeriodCatalog)
    assert answer.tool_trace[-1].outcome.information_cutoff == date(2026, 11, 11)
    assert AgentAnswer.model_validate_json(answer.model_dump_json()) == answer
    payload = json.loads(model.respond.call_args_list[0].kwargs["messages"][0].parts[0].content)
    assert payload["current_date"] == "2026-11-11" and payload["timezone"] == "Europe/Lisbon"
    assert payload["capabilities"]["financial_data_source"]["source"] == "financial_repository"
    assert payload["capabilities"]["financial_operations"]["available"] is True
    assert payload["capabilities"]["financial_operations"]["missing_application_inputs"] == []
    assert payload["capabilities"]["document_operations"]["available"] is False
    assert chat.ask("Why is availability uncertain?").tool_trace == []
    assert "list_financial_periods" in repr(model.respond.call_args.kwargs["messages"])


def test_unscoped_assessment_agent_can_explain_and_ask_for_application_selection():
    model = ScriptedModel(
        response=model_response(answer="Select a borrower in the app.", answer_kind="clarification")
    )
    agent = CreditAssessmentAgent(assessment_service=Mock(), model=model)
    answer = agent.ask("Calculate using the latest data")
    assert answer.complete and not answer.tool_trace
    payload = json.loads(model.respond.call_args.kwargs["messages"][0].parts[0].content)
    assert payload["capabilities"]["assessment_service_configured"] is True
    assert payload["capabilities"]["registered_tools"] == []
    assert payload["capabilities"]["financial_operations"]["missing_application_inputs"] == [
        "borrower_id"
    ]
    assert payload["capabilities"]["financial_operations"]["available"] is False
    assert payload["borrower_id"] is None


@pytest.mark.parametrize("assessment_configured", [False, True])
@pytest.mark.parametrize("ticker", [None, "FMC"])
def test_document_research_context_without_borrower(assessment_configured, ticker):
    documents = Mock()
    documents.list_document_extractions.return_value = []
    assessment = Mock() if assessment_configured else None
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("list_documents", {"ticker": "FMC"})),
        model_response(answer="No FMC documents are available.", answer_kind="discovery"),
    ]
    answer = CreditAssessmentAgent(
        service=documents, assessment_service=assessment, model=model
    ).ask("List FMC documents and their reported ratios.", ticker=ticker)
    assert answer.complete and answer.tool_trace[0].outcome == []
    documents.list_document_extractions.assert_called_once_with(ticker="FMC", include_results=False)
    if assessment is not None:
        assert assessment.mock_calls == []

    payload = json.loads(model.respond.call_args_list[0].kwargs["messages"][0].parts[0].content)
    assert payload["borrower_id"] is None and payload["selected_dates"] is None
    capabilities = payload["capabilities"]
    assert capabilities["document_operations"]["available"] is True
    assert capabilities["document_operations"]["required_application_inputs"] == []
    assert set(capabilities["registered_tools"]) == {
        "list_documents",
        "get_document_extraction",
        "search_evidence",
        "process_document",
    }
    if assessment_configured:
        financial = capabilities["financial_operations"]
        assert financial["available"] is False
        assert financial["required_application_input"] == "borrower_id"
        assert financial["missing_application_inputs"] == ["borrower_id"]
    else:
        assert "financial_operations" not in capabilities


@pytest.mark.parametrize("tool_names", [frozenset(), frozenset({"search_evidence"})])
def test_document_capability_availability_uses_registered_tools(tool_names):
    model = ScriptedModel(response=model_response(answer="Explain available capabilities."))
    CreditAssessmentAgent(service=Mock(), model=model, document_tool_names=tool_names).ask(
        "What can you do?"
    )
    payload = json.loads(model.respond.call_args.kwargs["messages"][0].parts[0].content)
    capabilities = payload["capabilities"]
    assert capabilities["document_service_configured"] is True
    assert capabilities["document_operations"]["available"] is bool(tool_names)
    assert set(capabilities["registered_tools"]) == tool_names
    assert "financial_operations" not in capabilities


def test_dates_from_saved_selection_remain_context_and_prompt_is_shared(service):
    snapshot = service.assess("SYN002", date(2025, 6, 30), date(2025, 7, 15), ml_enabled=False)
    model = ScriptedModel()
    chat = CreditAssessmentAgent(
        assessment_service=SavedAssessmentChat(Mock(), snapshot), model=model
    ).start_conversation(borrower_id="SYN002")
    chat.prime_evidence(snapshot)
    chat.ask(
        "Explain this snapshot", selected_dates=(snapshot.period_end, snapshot.information_cutoff)
    )
    payload = json.loads(model.respond.call_args.kwargs["messages"][0].parts[0].content)
    assert (
        payload["capabilities"]["financial_data_source"]["assessment_run_id"]
        == snapshot.assessment_run_id
    )
    assert payload["selected_dates"]["information_cutoff"] == "2025-07-15"
    assert model.respond.call_args.kwargs["info"].instructions.startswith(
        build_credit_assessment_instructions()
    )
    assert not hasattr(chat, "_pending_intent")
