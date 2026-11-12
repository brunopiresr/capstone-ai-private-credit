"""Concrete tool inputs are validated; request interpretation stays with the model."""

import json
from datetime import date
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.agents.tools.common import InvalidToolArguments
from credit_monitoring.domain.processing import DocumentExtraction

DATES = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}


@pytest.mark.parametrize(
    "dates",
    [
        {**DATES, "period_end": "2025-02-30"},
        {**DATES, "information_cutoff": "2025-06-30"},
        {**DATES, "information_cutoff": "not a date"},
    ],
)
@pytest.mark.parametrize("method", ["get_financials", "assess_covenants", "predict_risk"])
def test_invalid_dates_never_reach_services(dates, method):
    service = Mock()
    with pytest.raises(InvalidToolArguments):
        getattr(AssessmentTools(service, borrower_id="SYN002"), method)(**dates)
    assert service.mock_calls == []


@pytest.mark.parametrize("method", ["get_financials", "assess_covenants", "predict_risk"])
def test_selected_dates_reject_forecast_target_quarter_and_advanced_cutoff(method):
    service = Mock()
    tools = AssessmentTools(
        service, borrower_id="SYN002", selected_dates=(date(2025, 9, 30), date(2025, 9, 30))
    )
    for cutoff in ["2025-09-30", "2025-12-31"]:
        with pytest.raises(InvalidToolArguments, match="Use the selected period_end=2025-09-30"):
            getattr(tools, method)(period_end="2025-12-31", information_cutoff=cutoff)
    assert service.mock_calls == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"period_end": "2025-09-30"},
        {**DATES, "period_end": 20250930},
        {**DATES, "period_end": "2025-9-30"},
    ],
)
def test_graph_rejects_missing_or_mistyped_tool_inputs(arguments):
    service = Mock()
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_financials", arguments)),
        model_response(answer="Please clarify the dates.", answer_kind="clarification"),
    ]
    answer = CreditAssessmentAgent(assessment_service=service, model=model).ask(
        "Read the financials", borrower_id="SYN002"
    )
    assert answer.complete and answer.tool_trace[0].outcome.code == "invalid_arguments"
    assert service.mock_calls == []


@pytest.mark.parametrize(
    "question",
    [
        "Is SYN002 compliant?",
        "Can SYN008 comfortably cover its interest under the agreement?",
        "Does that springing thing even switch on?",
        "Switch to explaining the covenant",
        "Show evidence from 2025",
        "Assess for 03/04/2025",
        "Reporting period: September 2025",
    ],
)
def test_wording_reaches_model_without_routing_or_date_parsing(question):
    model = ScriptedModel(response=model_response(answer="Please supply the missing context."))
    answer = CreditAssessmentAgent(assessment_service=Mock(), model=model).ask(
        question, borrower_id="SYN002"
    )
    assert answer.complete and model.respond.call_count == 1
    info = model.respond.call_args.kwargs["info"]
    assert info.model_settings.get("tool_choice") is None
    assert "validated_request" not in model.respond.call_args.kwargs["messages"][0].parts[0].content


def test_scope_and_selected_dates_are_context_not_a_parsed_request():
    model = ScriptedModel()
    chat = CreditAssessmentAgent(assessment_service=Mock(), model=model).start_conversation(
        borrower_id="SYN002"
    )
    chat.ask("Explain", selected_dates=(date(2025, 9, 30), date(2025, 10, 15)))
    payload = json.loads(model.respond.call_args.kwargs["messages"][-1].parts[0].content)
    assert payload["borrower_id"] == "SYN002"
    assert payload["selected_dates"] == {
        "period_end": "2025-09-30",
        "information_cutoff": "2025-10-15",
    }


def test_clarification_and_topic_changes_use_history_without_pending_override():
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(
            answer="Which reporting date and information cutoff?", answer_kind="clarification"
        ),
        model_response(answer="Please provide the agreement.", answer_kind="evidence"),
    ]
    chat = CreditAssessmentAgent(assessment_service=Mock(), model=model).start_conversation(
        borrower_id="SYN002"
    )
    assert chat.ask("Predict risk").complete
    answer = chat.ask("Instead, explain this agreement from 2025")
    assert answer.complete and answer.answer_kind == "evidence" and not answer.tool_trace
    history = repr(model.respond.call_args.kwargs["messages"])
    assert "Predict risk" in history and "Instead, explain" in history
    assert not hasattr(chat, "_pending_intent")


def test_failed_processing_status_is_retained_for_follow_up():
    service = Mock()
    service.catalog_record.return_value = {"ticker": "FMC"}
    service.process_document.return_value = DocumentExtraction(
        document_id="FMC_AMD",
        citation="Amendment source",
        ticker="FMC",
        status="failed",
        error="Source unavailable",
    )
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("process_document", {"document_id": "FMC_AMD"})),
        model_response(answer="The source is unavailable.", gaps=["Processing failed."]),
        model_response(answer="Please provide the source document."),
    ]
    chat = CreditAssessmentAgent(service=service, model=model).start_conversation(ticker="FMC")
    first = chat.ask("Process the amendment")
    assert first.complete and any(entry.data.get("status") == "failed" for entry in first.evidence)
    assert chat.ask("What do you need?").complete
    assert "Source unavailable" in model.respond.call_args.kwargs["info"].instructions
