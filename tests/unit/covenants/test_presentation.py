"""Supplemental calculation facts supply context without changing financial service results."""

import json
from datetime import date

import pytest

from credit_monitoring.agents.evidence import EvidenceRegistry
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


def context_registry(assessment):
    registry = EvidenceRegistry()
    registry.record(assessment, borrower_id=assessment.borrower_id, ticker=None)
    return registry


@pytest.mark.parametrize(
    "case,observed,state,status",
    [
        ("H07", 18, "active", "breach"),
        ("H08", 25, "inactive", "not_tested"),
        ("H09", 40, "inactive", "not_tested"),
        ("E10", None, "unresolved", "unresolved"),
    ],
)
def test_springing_boundaries_and_missing_observations_are_available_in_context(
    case, observed, state, status, tmp_path
):
    assessment = captured(case, tmp_path)
    registry = context_registry(assessment)
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


def test_addback_explanation_reuses_existing_calculation_function_without_changing_result():
    assessment = captured("H06")
    original = assessment.model_dump_json()
    registry = context_registry(assessment)
    detail = next(
        e
        for e in registry.entries
        if e.kind == "calculation" and e.period_end == str(assessment.period_end)
    ).data["presentation"]["ebitda_explanation"]
    assert detail["allowed_addbacks"] == 5 and detail["covenant_ebitda"] == 30
    assert detail["cap_fraction"] == 0.2
    assert assessment.model_dump_json() == original


def test_waiver_periods_do_not_become_financial_satisfaction_or_an_invented_legal_expiry():
    assessment = captured("H11")
    registry = context_registry(assessment)
    current = next(
        e
        for e in registry.entries
        if e.kind == "calculation" and e.period_end == str(assessment.period_end)
    )
    relief = current.data["presentation"]["testing_relief"]
    assert relief["explicit_test_periods"] == ["2025-06-30", "2025-09-30"]
    assert relief["last_explicit_test_period"] == "2025-09-30"
    assert relief["legal_expiry_date"] is None
    assert current.data["financial_inputs"]["result_basis"] == "calculated"
