"""Saved analyst/manager handoffs, dated review evidence and frozen board reports."""

import json
from datetime import date

import pytest
from portfolio_helpers import portfolio_inputs, review_model
from pydantic_ai.messages import ModelRequest, UserPromptPart

from credit_monitoring.application.board_reporting import BoardReporting
from credit_monitoring.application.bootstrap import create_portfolio_service
from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.application.manager_workflow import ManagerWorkflow
from credit_monitoring.domain.credit_review import ExposureDecisionContext
from credit_monitoring.persistence.workflow_repository import WorkflowRepository

PERIOD = date(2025, 12, 31)
CUTOFF = PERIOD


@pytest.fixture
def manager(tmp_path):
    root = portfolio_inputs(tmp_path)
    model = review_model()
    portfolio = create_portfolio_service(
        data_root=root, working_dir=tmp_path / "working", model=model
    )
    analyst = BorrowerWorkflow(portfolio, portfolio.workflow_repository, root)
    return ManagerWorkflow(analyst), model


def submitted(manager, borrower="SYN001", *, period=date(2025, 9, 30), flag=True, review=False):
    analyst = manager.analyst
    assessment = analyst.assess(borrower, period, CUTOFF)
    rid = assessment.assessment_run_id
    if review:
        manager.portfolio.review(
            rid, ExposureDecisionContext(question="Review exposure.", credit_criteria=("Headroom",))
        )
    analyst.validate(rid, checks=(True, True, True), notes="Checked inputs and disclosed gaps.")
    if flag:
        analyst.flag(
            rid,
            category="Performance",
            severity="High",
            explanation=f"Review {borrower}.",
            action="Obtain an update.",
        )
    sid = analyst.save_report(
        rid,
        text=f"Analyst observations for {borrower}.",
        submit=True,
        triage="Monitor and obtain remediation if needed.",
    )
    return manager.repository.submission(sid)


def test_manager_decision_resolves_only_selected_flags_and_preserves_compliance(manager):
    service, _ = manager
    submission = submitted(service, "SYN002", period=PERIOD)
    assessment = service.assessment(submission)
    assert any(r.compliance_status == "breach" for r in assessment.results)
    flag_id = submission["payload"]["flags"][0]["flag_id"]
    service.record_note(
        submission["submission_id"],
        comment="Reviewed remediation.",
        recommendation="Maintain with monthly reporting.",
        reviewed=True,
        disposition="Resolve selected flags",
        resolve_ids=[flag_id],
    )
    reopened = WorkflowRepository(service.repository.database_path)
    assert reopened.flags("SYN002")[0]["payload"]["state"] == "resolved"
    assert service.state(submission) == "Reviewed"
    assert service.portfolio.repository.get_assessment(assessment.assessment_run_id) == assessment
    assert reopened.submission(submission["submission_id"]) == submission
    assert service.active_flags("SYN002") == []
    assert BoardReporting(service).sources(PERIOD, CUTOFF)["items"] == []


def test_new_assessment_submission_review_and_flags_require_fresh_manager_decision(manager):
    service, _ = manager
    original = submitted(service)
    service.record_note(
        original["submission_id"], comment="Checked.", recommendation="Monitor.", reviewed=True
    )
    fresh = submitted(service)
    assert service.state(fresh) == "Pending review"
    assert service.state(original) == "Superseded submission"
    with pytest.raises(ValueError, match="newer submissions"):
        service.record_note(
            original["submission_id"], comment="Old.", recommendation="Old.", reviewed=True
        )
    service.record_note(
        fresh["submission_id"], comment="New.", recommendation="Monitor.", reviewed=True
    )
    service.portfolio.review(
        fresh["run_id"], ExposureDecisionContext(question="Recheck.", credit_criteria=("Gaps",))
    )
    assert service.state(fresh) == "Pending review"
    service.analyst.flag(
        fresh["run_id"],
        category="Data quality",
        severity="Low",
        explanation="New reporting issue.",
        action="Reconcile.",
    )
    assert service.state(fresh) == "New flags awaiting submission"


def test_supplementary_review_uses_exact_saved_assessment_and_shared_dated_context(manager):
    service, model = manager
    submission = submitted(service, review=True)
    original = service.assessment(submission)
    original_review = submission["payload"]["review_id"]
    later = date(2026, 1, 15)
    rid = service.request_analysis(
        submission["submission_id"],
        kind="context",
        question="Assess collection delays.",
        context="Management expects customer receipts in February.",
        source="Management letter",
        available_at=later,
        review_cutoff=later,
    )
    result = service.run_requested_review(rid)
    assert result.status == "complete"
    assert result.review_id != original_review
    assert result.snapshot.information_cutoff == original.information_cutoff
    assert result.snapshot.review_information_cutoff == later
    assert result.snapshot.assessment_data["assessment_run_id"] == original.assessment_run_id
    assert len(service.portfolio.repository.assessment_history("SYN001")) == 1
    assert service.repository.submission(submission["submission_id"]) == submission
    assert service.repository.request(rid)["state"] == "response_ready"
    payloads = []
    for call in model.respond.call_args_list[-4:-1]:
        messages = call.kwargs["messages"]
        text = next(
            p.content
            for m in reversed(messages)
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        payloads.append(json.loads(text)["evidence_snapshot"])
    assert all(p["additional_context"] == payloads[0]["additional_context"] for p in payloads)
    assert payloads[0]["additional_context"][0]["source"] == "Management letter"
    assert (
        payloads[0]["additional_context"][0]["basis"]
        == "supplied source, not independently verified"
    )
    assert any(e["evidence_id"] == "context:0" for e in payloads[0]["evidence"])
    with pytest.raises(ValueError, match="outstanding requests"):
        service.record_note(
            submission["submission_id"], comment="Seen.", recommendation="Monitor.", reviewed=True
        )
    service.accept_response(rid, manager="Risk manager")
    service.record_note(
        submission["submission_id"],
        comment="Compared both versions.",
        recommendation="Monitor collections.",
        reviewed=True,
    )
    assert service.state(submission) == "Reviewed"
    assert service.repository.notes("SYN001")[0]["payload"]["review_id"] == result.review_id


def test_later_information_requires_updated_cutoff_and_unsourced_claims_stay_assumptions(manager):
    service, _ = manager
    submission = submitted(service)
    with pytest.raises(ValueError, match="Update the review cutoff"):
        service.request_analysis(
            submission["submission_id"],
            kind="context",
            question="Recheck.",
            available_at=date(2026, 1, 1),
        )
    rid = service.request_analysis(
        submission["submission_id"],
        kind="context",
        question="What if sales fall?",
        context="Sales could decline 20%.",
    )
    result = service.run_requested_review(rid)
    assert result.snapshot.prompt_context()["additional_context"][0]["basis"] == "assumption"
    assert result.snapshot.prompt_context()["additional_context"][0]["source"] is None


def test_incomplete_requested_review_is_retained_and_only_retries_explicitly(manager):
    service, model = manager
    submission = submitted(service, review=True)
    rid = service.request_analysis(
        submission["submission_id"], kind="context", question="Recheck gaps."
    )
    responding = model.respond.side_effect
    model.respond.side_effect = RuntimeError("Controlled model failure.")
    incomplete = service.run_requested_review(rid)
    assert incomplete.status == "incomplete"
    assert service.repository.request(rid)["state"] == "open"
    assert service.repository.request(rid)["payload"]["attempts"] == [incomplete.review_id]
    model.respond.side_effect = responding
    complete = service.run_requested_review(rid)
    assert complete.status == "complete"
    assert service.repository.request(rid)["state"] == "response_ready"
    assert len(service.portfolio.repository.review_history(submission["run_id"])) == 3
    with pytest.raises(ValueError, match="open context request"):
        service.run_requested_review(rid)


def test_correction_requires_recalculation_validation_resubmission_and_acceptance(manager):
    service, _ = manager
    original = submitted(service)
    request_id = service.request_analysis(
        original["submission_id"], kind="correction", question="Correct the EBITDA input."
    )
    with pytest.raises(ValueError, match="Recalculate"):
        service.respond(request_id, response="No change.", submission_id=original["submission_id"])
    with pytest.raises(ValueError, match="context request"):
        service.run_requested_review(request_id)
    assessment = service.analyst.assess(
        "SYN001",
        date(2025, 9, 30),
        CUTOFF,
        parent_id=original["run_id"],
        reason="Correct EBITDA.",
        overrides={"reported_ebitda": 29.0},
    )
    service.analyst.validate(
        assessment.assessment_run_id, checks=(True, True, True), notes="Corrected."
    )
    sid = service.analyst.save_report(
        assessment.assessment_run_id,
        text="Corrected inputs verified.",
        submit=True,
        triage="Retain the prior performance flag.",
    )
    service.respond(request_id, response="Recalculated and validated.", submission_id=sid)
    assert service.repository.request(request_id)["state"] == "response_ready"
    with pytest.raises(ValueError, match="outstanding requests"):
        service.record_note(sid, comment="Read.", recommendation="Maintain.", reviewed=True)
    service.accept_response(request_id)
    service.record_note(
        sid, comment="Correction reviewed.", recommendation="Maintain.", reviewed=True
    )
    assert service.state(service.repository.submission(sid)) == "Reviewed"


def test_source_changes_block_signoff_and_requests_can_be_cancelled_with_a_reason(manager):
    service, _ = manager
    submission = submitted(service)
    rid = service.request_analysis(submission["submission_id"], kind="context", question="Recheck.")
    service.repository.source_changed("SYN001", None, "New source.")
    with pytest.raises(ValueError, match="Sources changed"):
        service.run_requested_review(rid)
    with pytest.raises(ValueError, match="cancellation reason"):
        service.cancel_request(rid, reason="")
    service.cancel_request(rid, reason="Replaced by a financial correction request.")
    assert service.pending_requests("SYN001") == []
    with pytest.raises(ValueError, match="source changes"):
        service.record_note(
            submission["submission_id"], comment="Read.", recommendation="Maintain.", reviewed=True
        )


def test_report_register_includes_older_flags_missing_data_and_untriaged_breaches(manager):
    service, _ = manager
    submitted(service, "SYN003", period=date(2025, 6, 30))
    submitted(service, "SYN007")
    service.analyst.assess("SYN002", PERIOD, CUTOFF)
    service.analyst.assess("SYN005", date(2025, 9, 30), CUTOFF)
    sources = BoardReporting(service).sources(PERIOD, CUTOFF)
    items = {i["borrower_id"]: i for i in sources["items"]}
    assert set(items) == {"SYN002", "SYN003", "SYN007"}
    assert items["SYN003"]["assessment"]["period_end"] == "2025-06-30"
    assert items["SYN002"]["untriaged_breach"]
    assert items["SYN007"]["recommendation"] == "Pending manager review"
    assert sources["metrics"]["unassessed"] > 0
    assert sources["metrics"]["pending_reviews"] == 3


def test_final_report_is_frozen_and_pending_items_are_allowed_explicitly(manager):
    service, _ = manager
    submitted(service)
    reporting = BoardReporting(service)
    draft_id = reporting.generate(PERIOD, CUTOFF)
    final_id = reporting.save(
        draft_id,
        title="Board pack",
        summary="Pending analysis remains disclosed.",
        recommendations={"SYN001": "Obtain the missing analysis."},
        finalize=True,
    )
    frozen = service.repository.board_report(final_id)
    assert frozen["state"] == "final"
    assert frozen["payload"]["sources"]["items"][0]["review"] is None
    service.analyst.assess("SYN001", date(2025, 9, 30), CUTOFF)
    reopened = WorkflowRepository(service.repository.database_path)
    assert reopened.board_report(final_id) == frozen
    with pytest.raises(ValueError, match="Final reports are frozen"):
        reporting.save(final_id, title="Changed", summary="Changed", recommendations={})


def test_new_flags_require_draft_refresh_before_finalization(manager):
    service, _ = manager
    submitted(service)
    reporting = BoardReporting(service)
    draft = reporting.generate(PERIOD, CUTOFF)
    submitted(service, "SYN007")
    with pytest.raises(ValueError, match="Refresh the draft sources"):
        reporting.save(draft, title="Board", summary="Review", recommendations={}, finalize=True)
    refreshed = reporting.save(
        draft, title="Board", summary="Updated", recommendations={}, refresh=True
    )
    final = reporting.save(
        refreshed, title="Board", summary="Updated", recommendations={}, finalize=True
    )
    assert {
        i["borrower_id"]
        for i in service.repository.board_report(final)["payload"]["sources"]["items"]
    } == {"SYN001", "SYN007"}
