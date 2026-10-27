"""Shared exact tool contracts and final-answer criteria for live scenarios."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from credit_monitoring.agents.models import model_identity
from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.tool_results import FinancialReview

DATES = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}


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


def check_missing_financial_inputs_do_not_become_a_compliance_conclusion(
    answer: AgentAnswer,
) -> None:
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


def check_missing_dates_trigger_clarification_before_any_tools(answer: AgentAnswer) -> None:
    assert answer.tool_trace == [], answer.tool_trace


def check_stub_forecast_is_reported_as_unavailable(answer: AgentAnswer) -> None:
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


@dataclass(frozen=True)
class Scenario:
    name: str
    query: str
    borrower_id: str
    check: Callable[[AgentAnswer], None]
    criteria: tuple[str, ...]


SCENARIOS = (
    Scenario(
        "missing_financial_inputs",
        (
            "Assess SYN010's fixed charge coverage covenant. Reporting date: 2025-09-30. "
            "Information cutoff: 2025-09-30. Explain whether the covenant is active and "
            "whether compliance can be determined."
        ),
        "SYN010",
        check_missing_financial_inputs_do_not_become_a_compliance_conclusion,
        (
            (
                "The agent calls get_financials before assess_covenants, with both period_end"
                " and information_cutoff equal to 2025-09-30 for both calls, and does not "
                "call predict_risk."
            ),
            (
                "The answer explains that 20% revolver availability is below the 25% "
                "activation threshold, so the FCCR covenant is active, and reports its "
                "minimum requirement as 1.15x."
            ),
            (
                "The answer explains that compliance is incomplete because required financial"
                " inputs are missing. It invents no actual FCCR or headroom, claims neither "
                "compliance nor breach, and does not claim an actual FCCR of 1.10x."
            ),
        ),
    ),
    Scenario(
        "missing_dates",
        "Is SYN002 okay? Use the latest numbers.",
        "SYN002",
        check_missing_dates_trigger_clarification_before_any_tools,
        (
            (
                "The answer explicitly asks the analyst to provide BOTH the reporting date "
                "and the information cutoff before assessing SYN002."
            ),
            (
                "The agent makes no tool calls before asking for the missing dates, does not "
                "guess a date or quarter from 'latest', and reports no current compliance "
                "conclusion, ratio, or headroom."
            ),
        ),
    ),
    Scenario(
        "unavailable_forecast",
        (
            "What is SYN002's probability of breaching next quarter? Reporting date: "
            "2025-09-30. Information cutoff: 2025-09-30. Explain whether the configured "
            "model provides a forecast."
        ),
        "SYN002",
        check_stub_forecast_is_reported_as_unavailable,
        (
            (
                "The agent calls get_financials before predict_risk, with both period_end and"
                " information_cutoff equal to 2025-09-30 for both calls."
            ),
            (
                "The answer identifies the configured model as a stub and explains that no "
                "next-quarter breach probability is available. It invents no probability, "
                "does not interpret null as 0% risk, and does not present confidence as "
                "breach probability."
            ),
            (
                "The answer distinguishes unavailable future risk from current compliance: "
                "SYN002 is currently compliant, with leverage approximately 5.1923x, a "
                "maximum of 5.5x, and positive headroom approximately 0.3077x. Sensible "
                "rounding such as 5.19x and 0.31x is acceptable. Current compliance is not "
                "presented as low or zero future risk."
            ),
        ),
    ),
)


def capture_answer(directory: Path, scenario: Scenario, answer: AgentAnswer, model) -> None:
    """Save evidence before assertions, including incomplete and failed runs."""
    (directory / "agent-answer.json").write_text(answer.model_dump_json(indent=2))
    (directory / "request.json").write_text(
        json.dumps(
            {
                "question": scenario.query,
                "borrower_id": scenario.borrower_id,
                "model": model_identity(model),
                "criteria": scenario.criteria,
            },
            indent=2,
        )
    )


def check_scenario(scenario: Scenario, answer: AgentAnswer) -> None:
    assert answer.complete and answer.error is None, f"Agent failed: {answer.error}"
    scenario.check(answer)
