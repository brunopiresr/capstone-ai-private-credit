"""Real calculation/storage/agent composition, with only model responses controlled."""

import sqlite3
from datetime import date
from unittest.mock import Mock

import pytest
from portfolio_helpers import portfolio_inputs, review_model

from credit_monitoring.application.bootstrap import create_portfolio_service
from credit_monitoring.domain.credit_review import ExposureDecisionContext
from credit_monitoring.persistence.database import open_database

CUTOFF = date(2025, 12, 31)
PERIOD = date(2025, 9, 30)
CONTEXT = ExposureDecisionContext(
    question="Review this existing exposure.",
    credit_criteria=("Assess covenant compliance and gaps.",),
)


@pytest.fixture
def portfolio(tmp_path):
    data_root = portfolio_inputs(tmp_path)
    model = review_model()
    service = create_portfolio_service(
        data_root=data_root, working_dir=tmp_path / "working", model=model
    )
    return service, data_root, model


def test_initial_snapshot_has_all_borrowers_without_running_or_loading_labels(portfolio):
    service, data_root, model = portfolio
    assert not (data_root / "evaluation").exists()
    entries = service.snapshot(period_end=None, cutoff=CUTOFF)
    assert len(entries) == 12
    assert all(entry.assessment is None for entry in entries)
    targets = {entry.borrower_id: entry.period_end for entry in entries}
    assert targets["SYN003"] == date(2025, 6, 30)
    assert targets["SYN002"] == CUTOFF
    assert service.periods() == [date(2025, 3, 31), date(2025, 6, 30), PERIOD, CUTOFF]
    assert model.respond.call_count == 0
    assert all(
        set(borrower) == {"borrower_id", "borrower_name", "industry"}
        for borrower in service.borrowers
    )
    with open_database(service.assessment_service.settings.analytics_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM covenant_results").fetchone()[0] == 0


def test_batch_matches_real_rules_preserves_gaps_and_survives_reinitialization(portfolio, tmp_path):
    service, data_root, model = portfolio
    progress = []
    outcomes = service.assess(
        [b["borrower_id"] for b in service.borrowers],
        period_end=PERIOD,
        cutoff=CUTOFF,
        progress=lambda i, n, o: progress.append((i, n)),
    )
    assert len(outcomes) == 12
    assert not any(outcome.error for outcome in outcomes)
    assert progress[-1] == (12, 12)
    entries = {
        entry.borrower_id: entry for entry in service.snapshot(period_end=PERIOD, cutoff=CUTOFF)
    }
    assert entries["SYN001"].assessment.results[0].actual_value == pytest.approx(100 / 32)
    assert entries["SYN005"].statuses == {"waived"}
    assert entries["SYN007"].statuses == {"incomplete"}
    assert entries["SYN003"].needs_data  # No Q3 financials; never substitute its Q2 breach.
    assert entries["SYN003"].assessment.period_end == PERIOD
    assert model.respond.call_count == 0
    with open_database(service.financial_repository.database_path) as connection:
        connection.execute("DELETE FROM quarterly_financials WHERE borrower_id = 'SYN012'")
    reopened = create_portfolio_service(
        data_root=data_root, working_dir=tmp_path / "working", model=model
    )
    assert reopened.financial_repository.get_history("SYN012") == []  # Seed was not recopied.
    assert len(reopened.snapshot(period_end=PERIOD, cutoff=CUTOFF)) == 12
    assert (
        reopened.repository.get_assessment(entries["SYN001"].assessment.assessment_run_id)
        == entries["SYN001"].assessment
    )
    assert all(
        entry.assessment is None for entry in reopened.snapshot(period_end=PERIOD, cutoff=PERIOD)
    )
    missing = reopened.assess(["SYN012"], period_end=None, cutoff=CUTOFF)
    assert missing[0].error and missing[0].assessment is None


def test_failed_borrower_keeps_saved_results_without_stopping_the_batch(portfolio, monkeypatch):
    service, _, _ = portfolio
    saved = service.assess(["SYN001"], period_end=PERIOD, cutoff=CUTOFF)[0].assessment
    original = service.assessment_service.assess

    def assess(borrower_id, *args):
        if borrower_id == "SYN001":
            raise RuntimeError("private implementation detail")
        return original(borrower_id, *args)

    monkeypatch.setattr(service.assessment_service, "assess", assess)
    outcomes = service.assess(["SYN001", "SYN002"], period_end=PERIOD, cutoff=CUTOFF)
    assert outcomes[0].error and outcomes[1].assessment
    entry = next(
        item
        for item in service.snapshot(period_end=PERIOD, cutoff=CUTOFF)
        if item.borrower_id == "SYN001"
    )
    assert entry.assessment == saved and entry.last_error
    assert "private implementation detail" not in entry.last_error
    monkeypatch.setattr(service.assessment_service, "assess", original)
    service.assess(["SYN001"], period_end=PERIOD, cutoff=CUTOFF)
    assert (
        next(
            item
            for item in service.snapshot(period_end=PERIOD, cutoff=CUTOFF)
            if item.borrower_id == "SYN001"
        ).last_error
        is None
    )


def test_review_uses_exact_persisted_assessment_and_new_run_does_not_inherit_it(
    portfolio, monkeypatch
):
    service, _, model = portfolio
    assessment = service.assess(["SYN002"], period_end=PERIOD, cutoff=CUTOFF)[0].assessment
    original = service.assessment_service.assess
    monkeypatch.setattr(
        service.assessment_service,
        "assess",
        Mock(side_effect=AssertionError("Must not recalculate")),
    )
    review = service.review(assessment.assessment_run_id, CONTEXT)
    assert review.status == "complete"
    assert review.snapshot.assessment_run_id == assessment.assessment_run_id
    assert (
        review.snapshot.assessment_data["results"][0]["actual_value"]
        == assessment.results[0].actual_value
    )
    assert model.respond.call_count == 3
    assert service.repository.latest_review(assessment.assessment_run_id) == review
    assert "expected_metric" not in review.model_dump_json()
    monkeypatch.setattr(service.assessment_service, "assess", original)
    new = service.assess(["SYN002"], period_end=PERIOD, cutoff=CUTOFF)[0].assessment
    current = next(
        item
        for item in service.snapshot(period_end=PERIOD, cutoff=CUTOFF)
        if item.borrower_id == "SYN002"
    )
    assert new.assessment_run_id != assessment.assessment_run_id
    assert current.assessment == new and current.review is None
    assert service.repository.latest_review(assessment.assessment_run_id) == review
    with sqlite3.connect(service.repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_assessments").fetchone()[0] == 2


def test_unknown_ids_and_invalid_dates_do_not_start_runs(portfolio, monkeypatch):
    service, _, _ = portfolio
    mocked = Mock()
    monkeypatch.setattr(service.assessment_service, "assess", mocked)
    with pytest.raises(ValueError):
        service.assess(["SYN001", "UNKNOWN"], period_end=PERIOD, cutoff=CUTOFF)
    with pytest.raises(ValueError):
        service.assess(["SYN001"], period_end=CUTOFF, cutoff=PERIOD)
    assert mocked.call_count == 0


def test_optional_reviews_use_each_new_assessment_once(portfolio, monkeypatch):
    service, _, model = portfolio
    assess = Mock(wraps=service.assessment_service.assess)
    monkeypatch.setattr(service.assessment_service, "assess", assess)
    stages = []
    outcomes = service.assess(
        ["SYN001", "SYN002"],
        period_end=PERIOD,
        cutoff=CUTOFF,
        review_context=CONTEXT,
        stage_progress=lambda i, total, bid, stage: stages.append((bid, stage)),
    )
    assert assess.call_count == 2
    assert model.respond.call_count == 6
    assert len(stages) == 4
    assert stages[0][0] == stages[1][0] == "SYN001"
    assert stages[2][0] == stages[3][0] == "SYN002"
    for outcome in outcomes:
        assert outcome.review.status == "complete"
        assert outcome.review.snapshot.assessment_run_id == outcome.assessment.assessment_run_id
        assert outcome.review.snapshot.borrower_id == outcome.borrower_id
        assert outcome.review.decision_context == CONTEXT
        assert (
            service.repository.latest_review(outcome.assessment.assessment_run_id) == outcome.review
        )


def test_batch_continues_after_calculation_and_review_failures(portfolio, monkeypatch):
    service, _, model = portfolio
    original_assess = service.assessment_service.assess
    original_review = service.review
    review_ids = []

    def assess(borrower_id, *args):
        if borrower_id == "SYN001":
            raise RuntimeError("Calculation failed")
        return original_assess(borrower_id, *args)

    def review(run_id, context):
        assessment = service.repository.get_assessment(run_id)
        review_ids.append(assessment.borrower_id)
        if assessment.borrower_id == "SYN002":
            raise RuntimeError("Sensitive provider detail")
        return original_review(run_id, context)

    monkeypatch.setattr(service.assessment_service, "assess", assess)
    monkeypatch.setattr(service, "review", review)
    outcomes = service.assess(
        ["SYN001", "SYN002", "SYN004"],
        period_end=PERIOD,
        cutoff=CUTOFF,
        review_context=CONTEXT,
    )
    assert outcomes[0].error and outcomes[0].review is None
    assert outcomes[1].assessment and outcomes[1].error is None
    assert outcomes[1].review_error and "Sensitive provider detail" not in outcomes[1].review_error
    assert service.repository.get_assessment(outcomes[1].assessment.assessment_run_id)
    assert outcomes[2].review.status == "complete"
    assert review_ids == [
        "SYN002",
        "SYN004",
    ]  # No review of an older run after a failed calculation.
    assert model.respond.call_count == 3


def test_invalid_batch_review_criteria_reject_request_before_calculations(portfolio, monkeypatch):
    service, _, model = portfolio
    mocked = Mock()
    monkeypatch.setattr(service.assessment_service, "assess", mocked)
    with pytest.raises(ValueError, match="credit criterion"):
        service.assess(
            ["SYN001"],
            period_end=PERIOD,
            cutoff=CUTOFF,
            review_context=ExposureDecisionContext(question="Review the exposure."),
        )
    assert not mocked.called
    assert model.respond.call_count == 0
