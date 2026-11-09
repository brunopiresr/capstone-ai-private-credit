"""Exercise dispatch through real graphs; spies prove rejected services never ran."""

import asyncio
from datetime import date
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.request_policy import AnalystDate, resolve_request
from credit_monitoring.application.bootstrap import create_assessment_service
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.paths import APP_SYNTHETIC_DIR

DATES = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}
QUESTION = "Assess SYN002. Reporting date: 2025-09-30. Information cutoff: 2025-09-30."


@pytest.fixture
def scoped_service(tmp_path):
    database = tmp_path / "financial.db"
    load_financials(APP_SYNTHETIC_DIR / "synthetic_quarterly_financials.csv", database)
    return create_assessment_service(
        financial_repository=FinancialRepository(database),
        covenant_reader=SyntheticCovenantReader(APP_SYNTHETIC_DIR / "synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(analytics_database=tmp_path / "analytics.db"),
    )


@pytest.mark.parametrize(
    "question,missing",
    [
        ("Assess latest compliance", "reporting date and information cutoff"),
        ("Assess. Reporting date: 2025-09-30", "information cutoff"),
        ("Assess. Information cutoff: 2025-09-30", "reporting date"),
        ("Assess. Reporting date: 03/04/2025. Information cutoff: 2025-09-30", "unambiguous"),
        ("Assess. Reporting date: 2025-02-30. Information cutoff: 2025-09-30", "valid"),
        ("Assess. Reporting date: 2025-09-30. Information cutoff: 2025-06-30", "on or after"),
        ("Switch to SYN003. Reporting date: 2025-09-30. Information cutoff: 2025-09-30", "scoped"),
    ],
)
def test_invalid_requests_never_execute_financial_services(scoped_service, question, missing):
    scoped_service.assess = Mock()
    scoped_service.financial_repository.get_period_history = Mock()
    model = ScriptedModel()
    result = CreditAssessmentAgent(assessment_service=scoped_service, model=model).ask(
        question, borrower_id="SYN002"
    )
    assert result.complete and missing in result.answer
    scoped_service.assess.assert_not_called()
    scoped_service.financial_repository.get_period_history.assert_not_called()
    model.respond.assert_not_called()


@pytest.mark.parametrize("first_tool", ["assess_covenants", "predict_risk"])
def test_early_calls_wrong_forecasts_and_repeated_assessments_are_blocked(
    scoped_service, first_tool
):
    original = scoped_service.assess
    scoped_service.assess = Mock(wraps=original)
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response((first_tool, DATES)),
        model_response(("get_financials", DATES)),
        model_response(("assess_covenants", DATES)),
        model_response(("assess_covenants", DATES)),
        model_response(answer="Use the authoritative result."),
    ]
    answer = CreditAssessmentAgent(assessment_service=scoped_service, model=model).ask(
        QUESTION, borrower_id="SYN002"
    )
    assert answer.complete
    assert answer.tool_trace[0].outcome.code == "invalid_arguments"
    assert answer.tool_trace[3].outcome.code == "invalid_arguments"
    scoped_service.assess.assert_called_once()
    assert scoped_service.assess.call_args.kwargs == {"ml_enabled": False}


def test_failed_financial_read_does_not_admit_assessment(scoped_service):
    scoped_service.financial_repository.get_period_history = Mock(
        side_effect=OSError("Unavailable")
    )
    scoped_service.assess = Mock()
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_financials", DATES)),
        model_response(("assess_covenants", DATES)),
        model_response(answer="No financials"),
        model_response(answer="No financials"),
    ]
    answer = CreditAssessmentAgent(assessment_service=scoped_service, model=model).ask(
        QUESTION, borrower_id="SYN002"
    )
    assert not answer.complete
    scoped_service.assess.assert_not_called()


def test_successful_missing_financials_still_admit_authoritative_abstention(scoped_service):
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_financials", DATES)),
        model_response(("assess_covenants", DATES)),
        model_response(answer="The borrower has no mapped evidence."),
    ]
    answer = CreditAssessmentAgent(assessment_service=scoped_service, model=model).ask(
        QUESTION.replace("SYN002", "SYN999"), borrower_id="SYN999"
    )
    assert answer.complete
    assert answer.tool_trace[0].outcome.current is None
    assert answer.tool_trace[1].outcome.results == []


def test_changed_tool_dates_are_rejected_before_any_service_call(scoped_service):
    scoped_service.assess = Mock()
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_financials", {**DATES, "period_end": "2025-06-30"})),
        model_response(answer="Wrong dates"),
        model_response(answer="Wrong dates"),
    ]
    answer = CreditAssessmentAgent(assessment_service=scoped_service, model=model).ask(
        QUESTION, borrower_id="SYN002"
    )
    assert not answer.complete
    assert answer.tool_trace[0].outcome.code == "invalid_arguments"
    scoped_service.assess.assert_not_called()


def test_explicit_analyst_changes_replace_retained_dates():
    retained = {
        key: AnalystDate(date(2025, 9, 30), "2025-09-30") for key in ("reporting", "cutoff")
    }
    context = resolve_request(
        "Assess. Reporting date: 2025-06-30", borrower_id="SYN002", ticker=None, retained=retained
    )
    assert context.dates == {"period_end": "2025-06-30", "information_cutoff": "2025-09-30"}
    assert context.reporting.original_text == "reporting date: 2025-06-30"


def test_terminal_scope_dispatch_is_traced_once_and_ends_usefully(document_service_factory):
    service = document_service_factory()
    original = service.search_evidence
    service.search_evidence = Mock(wraps=original)
    model = ScriptedModel(
        response=model_response(("search_evidence", {"query": "leverage", "ticker": "OTHER"}))
    )
    answer = CreditAssessmentAgent(service=service, model=model).ask("Find evidence", ticker="SYN")
    assert answer.complete and "new scoped conversation" in answer.answer
    assert len(answer.tool_trace) == 1 and answer.tool_trace[0].outcome.terminal
    assert model.respond.call_count == 1
    service.search_evidence.assert_not_called()


def test_ui_dates_are_explicit_and_supplemental_analysis_cannot_supply_them(scoped_service):
    model = ScriptedModel()
    agent = CreditAssessmentAgent(assessment_service=scoped_service, model=model)
    chat = agent.start_conversation(borrower_id="SYN002")
    answer = asyncio.run(chat.ask_async("Assess", supplemental_context=QUESTION))
    assert "Please provide" in answer.answer
    assert not chat._dates


def test_forecast_intent_survives_date_clarification(scoped_service):
    model = ScriptedModel()
    model.respond.side_effect = [model_response(("get_financials", DATES)),
                                model_response(("predict_risk", DATES)),
                                model_response(answer="No forecast from a stub.")]
    chat = CreditAssessmentAgent(assessment_service=scoped_service, model=model).start_conversation(
        borrower_id="SYN002"
    )
    assert "Please provide" in chat.ask("Predict risk").answer
    result = chat.ask("Reporting date: 2025-09-30. Information cutoff: 2025-09-30.")
    assert result.complete
    assert [c.name for c in result.tool_trace] == ["get_financials", "predict_risk"]
