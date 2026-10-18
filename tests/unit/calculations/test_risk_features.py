"""Verify feature comparability and missing-period behavior over persisted results."""

from datetime import date
from pathlib import Path

import pytest

from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import CovenantResolution, FinancialPeriod
from credit_monitoring.features.model_features import model_feature_row
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
    for financials in financial_repository.get_period_history("SYN002", as_of=cutoff):
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


@pytest.mark.parametrize(
    "borrower_id,source_type,formula",
    [
        ("SYN002", "leverage", "net_leverage"),
        ("SYN004", "leverage", "total_leverage"),
        ("SYN012", "leverage", "pro_forma_leverage"),
        ("SYN008", "other", "interest_coverage"),
        ("SYN009", "other", "fixed_charge_coverage"),
    ],
)
def test_features_use_configured_formula_family(tmp_path, borrower_id, source_type, formula):
    database = tmp_path / "financials.sqlite3"
    load_financials(DATA / "synthetic_quarterly_financials.csv", database)
    period = date(2025, 9, 30)
    financials = FinancialRepository(database).get_period(borrower_id, period)
    reader = SyntheticCovenantReader(DATA / "synthetic_covenant_terms.csv")
    resolution = reader.resolve(borrower_id, period, period, financials)[0]
    assert resolution.covenant.formula == formula
    resolution.covenant_type = resolution.covenant.covenant_type = source_type
    result = calculate_covenant(
        resolution, financials, assessment_run_id="run", information_cutoff=period
    )
    repository = CovenantResultRepository(tmp_path / "analytics.sqlite3")
    repository.save_all([result])

    features = RiskFeatureBuilder(repository).build(
        borrower_id, period, period, assessment_run_id="run"
    )

    assert features.covenants[0].covenant_type == formula
    assert features.covenants[0].actual_value == result.actual_value
    row = model_feature_row(features)
    assert row[f"{formula}__covenant_count"] == 1
    assert row[f"{formula}__mean_actual_value"] == result.actual_value
    assert result.covenant_type == result.resolved_covenant.covenant_type == source_type
    assert repository.get_history(
        borrower_id, period_end=period, information_cutoff=period, assessment_run_id="run"
    ) == [result]


@pytest.mark.parametrize("covenant_name", ["Maximum Net Leverage", "Maximum Total Leverage"])
@pytest.mark.parametrize("resolved", [True, False], ids=["reported", "unresolved"])
def test_unmapped_leverage_is_not_inferred_from_its_name(result_history, covenant_name, resolved):
    repository, results = result_history
    current = results[-1]
    covenant = current.resolved_covenant
    covenant.covenant_type = "leverage"
    covenant.covenant_name = covenant_name
    covenant.formula = None
    covenant.reported_actual = 4.5
    covenant.reported_evidence = covenant.evidence
    result = calculate_covenant(
        CovenantResolution(
            covenant_id=current.covenant_id,
            covenant_type="leverage",
            covenant=covenant if resolved else None,
        ),
        FinancialPeriod.model_validate(current.financial_inputs["financial_period"]),
        assessment_run_id="run",
        information_cutoff=current.information_cutoff,
    )
    repository.save_all([result])
    features = RiskFeatureBuilder(repository).build(
        result.borrower_id, result.period_end, result.information_cutoff, assessment_run_id="run"
    )

    assert features.covenants[0].covenant_type == "leverage"
    with pytest.raises(ValueError, match="Unsupported covenant family"):
        model_feature_row(features)
    if resolved:
        assert result.financial_inputs["result_basis"] == "reported"
        assert result.actual_value == 4.5
        assert result.headroom == 1.0
        assert result.compliance_status == "compliant"
    else:
        assert result.compliance_status == "unresolved"
