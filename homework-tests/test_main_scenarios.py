"""Ask real analyst questions and check actual tools, arguments, and generated answers."""

import json

import pytest

from credit_monitoring.agents.models import model_identity
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.tool_results import FinancialReview

DATES = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}


def ask_and_capture(agent, artifact_dir, query, *, borrower_id):
    answer = agent.ask(query, borrower_id=borrower_id)
    capture = artifact_dir / "agent-answer.json"
    capture.write_text(answer.model_dump_json(indent=2), encoding="utf-8")
    (artifact_dir / "request.json").write_text(
        json.dumps(
            {"question": query, "borrower_id": borrower_id, "model": model_identity(agent.model)},
            indent=2,
        ),
        encoding="utf-8",
    )
    assert answer.complete, f"Agent failed: {answer.error}. See {capture}"
    assert answer.error is None
    return answer


def check_assessment_tools(answer, final_tool):
    names = [call.name for call in answer.tool_trace]
    assert names == ["get_financials", final_tool], names
    for call in answer.tool_trace:
        assert call.arguments == DATES, call
        assert isinstance(call.outcome, (FinancialReview, RiskAssessment)), call
    assessment = next(
        call.outcome for call in reversed(answer.tool_trace) if call.name == final_tool
    )
    assert isinstance(assessment, RiskAssessment)
    return assessment


def test_missing_financial_inputs_do_not_become_a_compliance_conclusion(
    credit_agent, scenario_artifacts
):
    query = (
        "Assess SYN010's fixed charge coverage covenant. Reporting date: 2025-09-30. "
        "Information cutoff: 2025-09-30. Explain whether the covenant is active and "
        "whether compliance can be determined."
    )
    answer = ask_and_capture(
        credit_agent,
        scenario_artifacts,
        query,
        borrower_id="SYN010",
    )

    assessment = check_assessment_tools(answer, "assess_covenants")
    assert assessment.borrower_id == "SYN010"
    result = assessment.results[0]
    assert result.compliance_status == "incomplete"
    assert result.actual_value is None and result.headroom is None
    assert result.threshold == pytest.approx(1.15)
    assert result.operator == ">="
    assert result.resolved_covenant.testing_status == "active"
    financials = answer.tool_trace[0].outcome
    assert isinstance(financials, FinancialReview)
    assert financials.current.metrics["revolver_availability_pct"] == 20
    assert financials.current.metrics["reported_ebitda"] is None


def test_missing_dates_trigger_clarification_before_any_tools(credit_agent, scenario_artifacts):
    query = "Is SYN002 okay? Use the latest numbers."
    answer = ask_and_capture(
        credit_agent,
        scenario_artifacts,
        query,
        borrower_id="SYN002",
    )

    assert answer.tool_trace == [], answer.tool_trace


def test_stub_forecast_is_reported_as_unavailable(credit_agent, scenario_artifacts):
    query = (
        "What is SYN002's probability of breaching next quarter? Reporting date: 2025-09-30. "
        "Information cutoff: 2025-09-30. Explain whether the configured model provides a forecast."
    )
    answer = ask_and_capture(
        credit_agent,
        scenario_artifacts,
        query,
        borrower_id="SYN002",
    )

    assessment = check_assessment_tools(answer, "predict_risk")
    assert assessment.borrower_id == "SYN002"
    assert assessment.ml_status == "stub"
    assert assessment.prediction is not None
    assert assessment.prediction.breach_probability is None
    assert assessment.prediction.risk_level == "unknown"
    assert assessment.results[0].compliance_status == "compliant"
    assert assessment.results[0].actual_value == pytest.approx(135 / 26)
    assert assessment.results[0].threshold == pytest.approx(5.5)
    assert assessment.results[0].headroom == pytest.approx(5.5 - 135 / 26)
