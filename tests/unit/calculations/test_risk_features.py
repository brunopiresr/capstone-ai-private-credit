"""Verify feature comparability and missing-period behavior over persisted results."""

from datetime import date
from pathlib import Path

import pytest

from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import FinancialPeriod
from credit_monitoring.features.risk_feature_builder import RiskFeatureBuilder
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.persistence.analytics_repositories import CovenantResultRepository

DATA = Path(__file__).resolve().parents[3] / "data"


@pytest.fixture
def result_history(tmp_path):
    database = tmp_path / "financials.sqlite3"
    load_financials(DATA / "synthetic_quarterly_financials.csv", database)
    financial_repository = FinancialRepository(database)
    reader = SyntheticCovenantReader(DATA / "synthetic_covenant_terms.csv")
    cutoff = date(2025, 9, 30)
    results = []
    for row in financial_repository.get_history("SYN002", as_of=cutoff.isoformat()):
        financials = FinancialPeriod.from_repository_row(row)
        resolution = reader.resolve("SYN002", financials.period_end, cutoff, financials)[0]
        results.append(
            calculate_covenant(
                resolution,
                financials,
                assessment_run_id="run",
                information_cutoff=cutoff,
            )
        )
    return CovenantResultRepository(tmp_path / "analytics.sqlite3"), results


def test_features_require_current_persisted_results(result_history):
    repository, results = result_history
    repository.save_all(results[:-1])
    with pytest.raises(ValueError, match="Persist current"):
        RiskFeatureBuilder(repository).build(
            "SYN002",
            date(2025, 9, 30),
            date(2025, 9, 30),
            assessment_run_id="run",
        )


def test_contractual_basis_change_suppresses_ratio_deltas(result_history):
    repository, results = result_history
    results[-1].resolved_covenant.cash_netting_cap = 20
    repository.save_all(results)
    features = (
        RiskFeatureBuilder(repository)
        .build(
            "SYN002",
            date(2025, 9, 30),
            date(2025, 9, 30),
            assessment_run_id="run",
        )
        .covenants[0]
    )
    assert features.basis_changed
    assert features.metric_change_qoq is None
    assert features.headroom_change_qoq is None


def test_threshold_change_is_separate_from_metric_change(result_history):
    repository, results = result_history
    results[-1].threshold += 0.5
    results[-1].resolved_covenant.threshold += 0.5
    results[-1].headroom += 0.5
    repository.save_all(results)
    features = (
        RiskFeatureBuilder(repository)
        .build(
            "SYN002",
            date(2025, 9, 30),
            date(2025, 9, 30),
            assessment_run_id="run",
        )
        .covenants[0]
    )
    assert not features.basis_changed
    assert features.threshold_change_qoq == 0.5
    assert features.headroom_change_qoq == pytest.approx(0.5 - features.metric_change_qoq)


def test_multiple_covenants_are_preserved(result_history):
    repository, results = result_history
    second = results[-1].model_copy(
        deep=True, update={"result_id": "second", "covenant_id": "other:lev"}
    )
    second.resolved_covenant.covenant_id = "other:lev"
    repository.save_all(results + [second])
    features = (
        RiskFeatureBuilder(repository)
        .build(
            "SYN002",
            date(2025, 9, 30),
            date(2025, 9, 30),
            assessment_run_id="run",
        )
        .covenants
    )
    assert len(features) == 2
    assert (
        next(item for item in features if item.covenant_id == "other:lev").previous_breach is None
    )
