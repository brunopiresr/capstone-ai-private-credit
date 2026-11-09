"""Required disclosures survive omitted model explanations; financial services stay unchanged."""

import json
from datetime import date

import pytest

from credit_monitoring.agents.answer_contract import finalize_content
from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.agents.presentation import forecast_label
from credit_monitoring.agents.request_policy import resolve_request
from credit_monitoring.domain.agent import AnswerContent
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.evaluation.agent_batch import SUITE, make_agent, read_scenarios
from credit_monitoring.paths import APP_SYNTHETIC_DIR


def captured(case, tmp_path=None):
    payload = json.loads(
        (SUITE / f"results/2026-11-09-baseline/cases/{case}/answer.json").read_text()
    )
    raw = (
        next(
            call["outcome"]
            for call in reversed(payload["tool_trace"])
            if "assessment_run_id" in call["outcome"]
        )
        if any("assessment_run_id" in c["outcome"] for c in payload["tool_trace"])
        else None
    )
    if raw is not None:
        return RiskAssessment.model_validate(raw)
    scenario = next(c for c in read_scenarios(SUITE / "scenarios.csv") if c.scenario_id == case)
    service = make_agent(scenario, tmp_path, "unused", APP_SYNTHETIC_DIR).assessment_service
    return service.assess(
        scenario.borrower_id,
        date.fromisoformat(scenario.period_end),
        date.fromisoformat(scenario.information_cutoff),
        ml_enabled=False,
    )


def render(assessment):
    registry = EvidenceRegistry()
    registry.record(assessment, borrower_id=assessment.borrower_id, ticker=None)
    intent = "Predict risk" if assessment.ml_status != "disabled" else "Assess"
    context = resolve_request(
        f"{intent}. Reporting date: {assessment.period_end}. "
        f"Information cutoff: {assessment.information_cutoff}.",
        borrower_id=assessment.borrower_id,
        ticker=None,
    )
    content = finalize_content(
        AnswerContent(
            schema_version="agent-answer-v2",
            answer="Results.",
            confidence="medium",
            confidence_explanation="Source limitations.",
        ),
        registry,
        context,
        {assessment.assessment_run_id},
    )
    return registry, content


@pytest.mark.parametrize(
    "case,observed,state,status",
    [
        ("H07", 18, "active", "breach"),
        ("H08", 25, "inactive", "not_tested"),
        ("H09", 40, "inactive", "not_tested"),
        ("E10", None, "unresolved", "unresolved"),
    ],
)
def test_springing_boundaries_and_missing_observations_are_rendered(
    case, observed, state, status, tmp_path
):
    assessment = captured(case, tmp_path)
    registry, output = render(assessment)
    entry = next(
        e
        for e in registry.entries
        if e.kind == "calculation" and e.period_end == str(assessment.period_end)
    )
    springing = entry.data["presentation"]["springing"]
    assert springing["observed_availability_pct"] == observed
    assert springing["trigger_threshold_pct"] == 25
    assert springing["trigger_direction"] == "<"
    assert springing["testing_status"] == state and springing["assessment_status"] == status
    assert "Observed availability pct" in output.answer
    if observed is None:
        assert "null" in output.answer


def test_addback_explanation_reuses_existing_calculation_function_without_changing_result():
    assessment = captured("H06")
    original = assessment.model_dump_json()
    registry, output = render(assessment)
    detail = next(
        e
        for e in registry.entries
        if e.kind == "calculation" and e.period_end == str(assessment.period_end)
    ).data["presentation"]["ebitda_explanation"]
    assert detail["allowed_addbacks"] == 5 and detail["covenant_ebitda"] == 30
    assert detail["cap_fraction"] == 0.2
    assert "Allowed addbacks" in output.answer
    assert assessment.model_dump_json() == original


def test_waiver_periods_do_not_become_financial_satisfaction_or_an_invented_legal_expiry():
    assessment = captured("H11")
    registry, output = render(assessment)
    current = next(
        e
        for e in registry.entries
        if e.kind == "calculation" and e.period_end == str(assessment.period_end)
    )
    relief = current.data["presentation"]["testing_relief"]
    assert relief["explicit_test_periods"] == ["2025-06-30", "2025-09-30"]
    assert relief["last_explicit_test_period"] == "2025-09-30"
    assert relief["legal_expiry_date"] is None
    assert "repayment strength" in output.answer and "null (unavailable)" in output.answer
    assert current.data["financial_inputs"]["result_basis"] == "calculated"


@pytest.mark.parametrize("case", ["H14", "H15", "E08", "E09", "E11", "B04", "B05", "B06"])
def test_forecast_metadata_nulls_conflicts_and_limitations_survive_absent_model_explanation(case):
    assessment = captured(case)
    _, output = render(assessment)
    for issue in assessment.issues:
        assert issue in output.answer
    assert str(assessment.period_end) in output.answer
    assert "individual" in output.answer and "not generated interpretation" in output.answer
    if assessment.prediction:
        assert assessment.prediction.model_version in output.answer
        assert str(assessment.prediction.snapshot_id) in output.answer
        assert "next-quarter horizon" in output.answer
    if assessment.prediction and assessment.prediction.model_name == "logistic_regression":
        assert "synthetic" in output.answer


def test_forecast_asof_date_is_never_named_as_the_future_quarter_end():
    label = forecast_label({"period_end": "2025-09-30", "horizon_quarters": 1})
    assert label.startswith("Forecast as of 2025-09-30, next-quarter horizon")
    assert "Target period end is not supplied" in label
