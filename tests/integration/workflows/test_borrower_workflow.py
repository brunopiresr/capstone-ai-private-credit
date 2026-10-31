"""Real calculations, version-bound analyst decisions, and immutable report handoffs."""

from datetime import date

import pytest
from model_helpers import ScriptedModel, model_response
from portfolio_helpers import portfolio_inputs, review_model

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.tools.sources import result_sources
from credit_monitoring.application.bootstrap import create_portfolio_service
from credit_monitoring.application.borrower_workflow import BorrowerWorkflow, SavedAssessmentChat
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import ExposureDecisionContext
from credit_monitoring.domain.tool_results import FinancialReview
from credit_monitoring.persistence.workflow_repository import WorkflowRepository

PERIOD = date(2025, 9, 30)
CUTOFF = date(2025, 12, 31)


@pytest.fixture
def workflow(tmp_path):
    root = portfolio_inputs(tmp_path)
    service = create_portfolio_service(
        data_root=root, working_dir=tmp_path / "working", model=review_model()
    )
    return BorrowerWorkflow(service, WorkflowRepository(tmp_path / "workflow.sqlite3"), root)


def validate(workflow, assessment, notes="Reviewed source availability warnings."):
    workflow.validate(assessment.assessment_run_id, checks=(True, True, True), notes=notes)


def test_enabling_ml_preserves_saved_inputs_and_old_versions(workflow):
    original = workflow.assess("SYN001", PERIOD, CUTOFF, prediction_mode="Off")
    revised = workflow.assess(
        "SYN001",
        PERIOD,
        CUTOFF,
        prediction_mode="Off",
        parent_id=original.assessment_run_id,
        reason="Correct EBITDA.",
        overrides={"reported_ebitda": 25.0},
    )
    validate(workflow, revised)
    enabled = workflow.enable_ml(revised.assessment_run_id)
    assert enabled.ml_status == "complete"
    assert enabled.prediction.model_name == "logistic_regression"
    assert 0 <= enabled.prediction.breach_probability <= 1
    assert enabled.results[0].actual_value == revised.results[0].actual_value
    assert enabled.results[0].financial_inputs == revised.results[0].financial_inputs
    assert (
        enabled.results[0].financial_inputs["financial_period"]["metrics"]["reported_ebitda"] == 25
    )
    assert (
        workflow.portfolio.repository.get_assessment(revised.assessment_run_id).ml_status
        == "disabled"
    )
    assert workflow.validation(revised.assessment_run_id)
    assert workflow.validation(enabled.assessment_run_id) is None


def test_breach_handoff_requires_validation_and_triage_and_survives_restart(workflow):
    assessment = workflow.assess("SYN002", CUTOFF, CUTOFF)
    rid = assessment.assessment_run_id
    assert any(r.compliance_status == "breach" for r in assessment.results)
    with pytest.raises(ValueError, match="Validate this"):
        workflow.save_report(rid, text="Debt requires remediation.", submit=True)
    validate(workflow, assessment)
    with pytest.raises(ValueError, match="Flag this breach"):
        workflow.save_report(rid, text="Debt requires remediation.", submit=True)
    workflow.flag(
        rid,
        category="Covenant breach",
        severity="High",
        explanation="Leverage breach.",
        action="Obtain a remediation plan.",
    )
    submission_id = workflow.save_report(rid, text="Debt requires remediation.", submit=True)
    reopened = WorkflowRepository(workflow.repository.database_path)
    saved = reopened.submissions()[0]
    assert saved["submission_id"] == submission_id
    assert saved["payload"]["assessment"] == assessment.model_dump(mode="json")
    assert saved["payload"]["review_id"] is None
    assert saved["payload"]["flags"][0]["run_id"] == rid
    workflow.save_report(rid, text="Changed draft.")
    workflow.assess("SYN002", PERIOD, CUTOFF)
    assert reopened.submissions()[0] == saved


def test_revisions_preserve_sources_parent_runs_and_signoff_and_accumulate_changes(workflow):
    old = workflow.assess("SYN001", PERIOD, CUTOFF)
    validate(workflow, old)
    source = workflow.portfolio.financial_repository.get_period("SYN001", PERIOD)
    new = workflow.assess(
        "SYN001",
        PERIOD,
        CUTOFF,
        parent_id=old.assessment_run_id,
        overrides={"reported_ebitda": 10.0},
        reason="Revised certificate.",
    )
    assert new.results[0].actual_value != old.results[0].actual_value
    assert workflow.validation(new.assessment_run_id) is None
    assert workflow.validation(old.assessment_run_id)
    assert workflow.portfolio.financial_repository.get_period("SYN001", PERIOD) == source
    next_run = workflow.assess(
        "SYN001",
        PERIOD,
        CUTOFF,
        parent_id=new.assessment_run_id,
        overrides={"eligible_addbacks": 0.0},
        reason="Remove addbacks.",
    )
    inputs = next_run.results[0].financial_inputs["financial_period"]["metrics"]
    assert inputs["reported_ebitda"] == 10
    assert inputs["eligible_addbacks"] == 0
    assert workflow.portfolio.repository.get_assessment(old.assessment_run_id) == old
    assert (
        workflow.repository.events(new.assessment_run_id, "run")[0]["payload"]["parent_id"]
        == old.assessment_run_id
    )


def test_missing_inputs_require_exceptions_and_structured_errors_block_validation(workflow):
    assessment = workflow.assess("SYN007", PERIOD, CUTOFF)
    assert workflow.needs_exceptions(assessment)
    with pytest.raises(ValueError, match="missing data"):
        validate(workflow, assessment, notes="")
    validate(workflow, assessment, notes="Debt sources disagree; request a reconciled certificate.")
    workflow.save_report(
        assessment.assessment_run_id, text="Compliance conclusion deferred.", submit=True
    )
    broken = assessment.model_copy(deep=True)
    broken.assessment_run_id = "invalid-verification"
    broken.verification.add("error", "broken", "results", "Invalid calculation.")
    workflow.portfolio.repository.save_assessment(broken)
    with pytest.raises(ValueError, match="verification errors"):
        validate(workflow, broken)


def test_review_versions_invalidate_validation_and_submission_freezes_exact_review(workflow):
    assessment = workflow.assess("SYN001", PERIOD, CUTOFF)
    rid = assessment.assessment_run_id
    context = ExposureDecisionContext(question="Review exposure.", credit_criteria=("Headroom",))
    first = workflow.portfolio.review(rid, context)
    validate(workflow, assessment)
    workflow.save_report(rid, text="Maintain with monitoring.", submit=True)
    frozen = workflow.repository.submissions()[0]
    assert frozen["payload"]["review_id"] == first.review_id
    second = workflow.portfolio.review(rid, context)
    assert workflow.validation(rid) is None
    assert workflow.repository.submissions()[0] == frozen
    validate(workflow, assessment)
    workflow.save_report(rid, text="Updated observations.", submit=True)
    assert workflow.repository.submissions()[0]["payload"]["review_id"] == second.review_id
    assert len(workflow.portfolio.repository.review_history(rid)) == 2


def test_chat_reads_saved_facts_and_explicit_recalculation_uses_workflow_save(workflow):
    assessment = workflow.assess("SYN001", PERIOD, CUTOFF)
    adapter = SavedAssessmentChat(workflow, assessment)
    initial = len(workflow.portfolio.repository.assessment_history("SYN001"))
    assert adapter.assess("SYN001", PERIOD, CUTOFF, ml_enabled=False) == assessment
    assert len(workflow.portfolio.repository.assessment_history("SYN001")) == initial
    with pytest.raises(ValueError, match="selection"):
        adapter.assess("SYN002", PERIOD, CUTOFF)
    adapter.allow_recalculation = True
    adapter.reason = "Refresh calculations at analyst request."
    new = adapter.assess("SYN001", PERIOD, CUTOFF, ml_enabled=False)
    assert new.assessment_run_id != assessment.assessment_run_id
    assert workflow.portfolio.repository.get_assessment(new.assessment_run_id) == new
    assert workflow.validation(new.assessment_run_id) is None
    adapter.assess("SYN001", PERIOD, CUTOFF)
    assert len(workflow.portfolio.repository.assessment_history("SYN001")) == initial + 1


def test_existing_agent_tools_can_read_saved_assessment_without_recalculating(workflow):
    assessment = workflow.assess("SYN001", PERIOD, CUTOFF)
    adapter = SavedAssessmentChat(workflow, assessment)
    model = ScriptedModel()
    dates = {"period_end": PERIOD.isoformat(), "information_cutoff": CUTOFF.isoformat()}
    model.respond.side_effect = [
        model_response(("get_financials", dates)),
        model_response(("assess_covenants", dates)),
        model_response(answer="The saved leverage is 3.12x."),
    ]
    conversation = CreditAssessmentAgent(
        assessment_service=adapter, model=model
    ).start_conversation(borrower_id="SYN001")
    answer = conversation.ask("Explain this saved assessment.")
    assert answer.complete
    assert [t.name for t in answer.tool_trace] == ["get_financials", "assess_covenants"]
    assert isinstance(answer.tool_trace[0].outcome, FinancialReview)
    assert isinstance(answer.tool_trace[1].outcome, RiskAssessment)
    assert answer.tool_trace[1].outcome.assessment_run_id == assessment.assessment_run_id
    assert answer.sources == result_sources(assessment)
    assert len(workflow.portfolio.repository.assessment_history("SYN001")) == 1


@pytest.mark.parametrize(
    "overrides,reason",
    [({"notes": 1}, "Changed"), ({"cash": float("nan")}, "Changed"), ({"cash": 1}, "")],
)
def test_invalid_revisions_never_create_a_saved_version(workflow, overrides, reason):
    assessment = workflow.assess("SYN001", PERIOD, CUTOFF)
    with pytest.raises(ValueError):
        workflow.assess(
            "SYN001",
            PERIOD,
            CUTOFF,
            parent_id=assessment.assessment_run_id,
            overrides=overrides,
            reason=reason,
        )
    assert len(workflow.portfolio.repository.assessment_history("SYN001")) == 1
