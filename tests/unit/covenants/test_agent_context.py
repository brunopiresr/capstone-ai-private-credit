"""Model-facing context assembly and result caveats; all model requests are mocked."""

from datetime import date
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.prompts.credit_assessment import (
    ASSESSMENT_INSTRUCTIONS,
    ASSESSMENT_UNAVAILABLE_INSTRUCTIONS,
    CONFIDENCE_INSTRUCTIONS,
    CREDIT_ASSESSMENT_INSTRUCTIONS,
    build_credit_assessment_instructions,
)
from credit_monitoring.agents.tools.assessment import AssessmentTools
from credit_monitoring.domain import (
    BorrowerFeatureSnapshot,
    BorrowerRiskFeatures,
    CovenantResult,
    RiskAssessment,
    RiskPrediction,
)

PERIOD = date(2025, 9, 30)
STUB_CAVEAT = "The configured model is a stub; no forecast or risk probability is available."
UNAVAILABLE_CAVEAT = (
    "Model output is unavailable; deterministic results retain their reported status."
)
SYNTHETIC_CAVEAT = (
    "The Logistic Regression baseline was trained and evaluated on synthetic "
    "borrower histories, not real credit outcomes."
)
AVAILABILITY_CAVEAT = (
    "Source availability dates are unknown; point-in-time forecast reliability is not established."
)


def test_assessment_only_agent_requires_borrower_scope_and_has_no_document_tools():
    model = ScriptedModel()
    agent = CreditAssessmentAgent(assessment_service=Mock(), model=model)
    with pytest.raises(ValueError, match="borrower ID"):
        agent.start_conversation()
    with pytest.raises(ValueError, match="borrower ID"):
        agent.ask("Summarize the assessment")
    with pytest.raises(ValueError, match="document service"):
        agent.start_conversation(borrower_id="SYN", ticker="SYN")
    conversation = agent.start_conversation(borrower_id="SYN")
    assert conversation.ask("Summarize the assessment").complete
    assert {tool.name for tool in model.respond.call_args.kwargs["info"].function_tools} == {
        "get_financials",
        "assess_covenants",
        "predict_risk",
    }
    with pytest.raises(ValueError, match="document or assessment service"):
        CreditAssessmentAgent(model=model)


@pytest.mark.parametrize("assessment_enabled", [False, True])
def test_agent_sends_only_context_for_registered_tools(assessment_enabled):
    model = ScriptedModel()
    agent = CreditAssessmentAgent(service=Mock(), assessment_service=Mock(), model=model)
    answer = agent.ask("Summarize evidence", borrower_id="SYN" if assessment_enabled else None)
    assert answer.complete
    info = model.respond.call_args.kwargs["info"]
    instructions = info.instructions
    assert instructions == build_credit_assessment_instructions(
        assessment_enabled=assessment_enabled
    )
    # Includes the explicit date gate and financial-read sequences validated live.
    assert len(instructions.split()) <= 450
    assert CREDIT_ASSESSMENT_INSTRUCTIONS.strip() in instructions
    assert CONFIDENCE_INSTRUCTIONS.strip() in instructions
    assert (ASSESSMENT_INSTRUCTIONS.strip() in instructions) is assessment_enabled
    assert (ASSESSMENT_UNAVAILABLE_INSTRUCTIONS.strip() in instructions) is not assessment_enabled
    assessment_names = {"get_financials", "assess_covenants", "predict_risk"}
    assert {tool.name for tool in info.function_tools} & assessment_names == (
        assessment_names if assessment_enabled else set()
    )


@pytest.fixture
def assessment_result():
    return RiskAssessment(
        assessment_run_id="run_synthetic",
        borrower_id="SYN",
        period_end=PERIOD,
        information_cutoff=PERIOD,
        results=[
            CovenantResult(
                result_id="result_synthetic",
                assessment_run_id="run_synthetic",
                borrower_id="SYN",
                covenant_id="leverage",
                covenant_type="total_leverage",
                period_end=PERIOD,
                information_cutoff=PERIOD,
                actual_value=3.5,
                threshold=4.0,
                headroom=0.5,
                compliance_status="compliant",
                financial_inputs={"result_basis": "calculated"},
                issues=["Existing calculation issue"],
            )
        ],
        issues=["Existing service issue"],
    )


@pytest.mark.parametrize("method", ["assess_covenants", "predict_risk"])
@pytest.mark.parametrize(
    "status,model_name,expected_caveats",
    [
        ("disabled", None, []),
        ("stub", "stub", [STUB_CAVEAT]),
        ("complete", "logistic_regression", [SYNTHETIC_CAVEAT]),
        ("complete", "custom_model", []),
        ("failed", "logistic_regression", [UNAVAILABLE_CAVEAT]),
        ("unavailable", "logistic_regression", [UNAVAILABLE_CAVEAT]),
    ],
)
def test_assessment_tools_describe_only_applicable_model_limitations(
    assessment_result, method, status, model_name, expected_caveats
):
    assessment_result.ml_status = status
    if model_name is not None:
        assessment_result.prediction = RiskPrediction(
            borrower_id="SYN",
            period_end=PERIOD,
            model_name=model_name,
            model_version="v1",
            prediction_status=status,
            breach_probability=0.25 if status == "complete" else None,
        )
    original = assessment_result.model_copy(deep=True)
    service = Mock()
    service.assess.return_value = assessment_result
    tools = AssessmentTools(service, borrower_id="SYN")
    result = getattr(tools, method)(PERIOD.isoformat(), PERIOD.isoformat())

    service.assess.assert_called_once_with(
        "SYN", PERIOD, PERIOD, ml_enabled=method == "predict_risk"
    )
    assert result is not assessment_result
    assert result.issues == ["Existing service issue", *expected_caveats]
    assert result.model_dump(exclude={"issues"}) == original.model_dump(exclude={"issues"})
    assert assessment_result == original
    assert RiskAssessment.model_validate_json(result.model_dump_json()) == result

    # Caller mutations must not reach nested calculation, prediction or verification data.
    result.results[0].financial_inputs["result_basis"] = "changed"
    result.results[0].issues.append("Changed by consumer")
    result.verification.is_valid = False
    if result.prediction is not None:
        result.prediction.model_version = "changed"
    assert assessment_result == original


@pytest.mark.parametrize(
    "availability,expected_caveats",
    [
        ("absent", []),
        ("unrelated_warning", []),
        ("known_snapshot", []),
        ("warning", [AVAILABILITY_CAVEAT]),
        ("unknown_snapshot", [AVAILABILITY_CAVEAT]),
        ("both", [AVAILABILITY_CAVEAT]),
    ],
)
def test_unknown_availability_uses_verification_or_snapshot_and_preserves_sources(
    assessment_result, availability, expected_caveats
):
    if availability in {"warning", "both", "unrelated_warning"}:
        assessment_result.verification.add(
            "warning",
            "other_warning"
            if availability == "unrelated_warning"
            else "information_availability_unknown",
            "results[0]",
            "Existing verification warning",
        )
    if availability in {"known_snapshot", "unknown_snapshot", "both"}:
        assessment_result.feature_snapshot = BorrowerFeatureSnapshot(
            assessment_run_id="run_synthetic",
            features=BorrowerRiskFeatures(
                borrower_id="SYN",
                period_end=PERIOD,
                information_cutoff=PERIOD,
                information_availability_known=availability == "known_snapshot",
            ),
            source_result_ids=["result_synthetic"],
        )
    original = assessment_result.model_copy(deep=True)
    service = Mock()
    service.assess.return_value = assessment_result
    tools = AssessmentTools(service, borrower_id="SYN")
    result = tools.predict_risk(PERIOD.isoformat(), PERIOD.isoformat())

    assert result.issues == ["Existing service issue", *expected_caveats]
    assert result.model_dump(exclude={"issues"}) == original.model_dump(exclude={"issues"})
    assert assessment_result == original
    if result.feature_snapshot is not None:
        result.feature_snapshot.source_result_ids.clear()
        result.feature_snapshot.features.information_availability_known = False
        assert assessment_result == original


def test_enriching_existing_caveats_is_idempotent(assessment_result):
    assessment_result.ml_status = "stub"
    assessment_result.issues.extend([STUB_CAVEAT, AVAILABILITY_CAVEAT])
    assessment_result.verification.add(
        "warning", "information_availability_unknown", "results[0]", "Availability unknown"
    )
    service = Mock()
    service.assess.return_value = assessment_result
    tools = AssessmentTools(service, borrower_id="SYN")
    first = tools.predict_risk(PERIOD.isoformat(), PERIOD.isoformat())
    service.assess.return_value = first
    second = tools.predict_risk(PERIOD.isoformat(), PERIOD.isoformat())
    assert second == first == assessment_result
    assert second is not first and first is not assessment_result
    assert second.issues == ["Existing service issue", STUB_CAVEAT, AVAILABILITY_CAVEAT]
