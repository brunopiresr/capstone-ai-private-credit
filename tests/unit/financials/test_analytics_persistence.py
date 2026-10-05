"""Validate analytics constraints and append-only repository behavior."""

import sqlite3
from datetime import date

import pytest

from credit_monitoring.config.settings import RiskModelConfig
from credit_monitoring.domain.assessment import CovenantResult, FinancialPeriod
from credit_monitoring.domain.risk_features import (
    BorrowerFeatureSnapshot,
    BorrowerRiskFeatures,
    CovenantRiskFeatures,
)
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.ml.factory import RiskModelFactory
from credit_monitoring.persistence.analytics_repositories import (
    CovenantResultRepository,
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
    initialize_analytics,
)


@pytest.fixture
def records(tmp_path):
    database = tmp_path / "analytics.sqlite3"
    initialize_analytics(database)
    initialize_analytics(database)
    period = date(2025, 9, 30)
    financials = FinancialPeriod(borrower_id="BORROWER", period_end=period)
    result = CovenantResult(
        assessment_run_id="run-1",
        borrower_id="BORROWER",
        covenant_id="agreement:lev",
        covenant_type="leverage",
        period_end=period,
        information_cutoff=period,
        compliance_status="unresolved",
        financial_inputs={
            "financial_period": financials.model_dump(mode="json"),
            "result_basis": "unavailable",
        },
    )
    results = CovenantResultRepository(database)
    results.save_all([result])
    features = BorrowerRiskFeatures(
        borrower_id="BORROWER",
        period_end=period,
        information_cutoff=period,
        covenants=[
            CovenantRiskFeatures(
                covenant_id=result.covenant_id,
                covenant_type="leverage",
                compliance_status="unresolved",
            )
        ],
    )
    snapshot = BorrowerFeatureSnapshot(
        assessment_run_id="run-1",
        features=features,
        source_result_ids=[result.result_id],
    )
    return database, results, result, snapshot


def test_result_round_trip_duplicate_and_atomic_batch(records):
    database, repository, result, _ = records
    assert repository.get_history(
        "BORROWER",
        period_end=result.period_end,
        information_cutoff=result.information_cutoff,
    ) == [result]
    second = result.model_copy(update={"result_id": "new", "assessment_run_id": "run-2"})
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_all([second, result])
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM covenant_results").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["missing", "borrower", "future", "run", "covenant"])
def test_snapshot_reference_validation(records, change):
    database, _, _, snapshot = records
    if change == "missing":
        snapshot.source_result_ids = ["missing"]
    elif change == "borrower":
        snapshot.features.borrower_id = "OTHER"
    elif change == "future":
        snapshot.features.period_end = date(2025, 6, 30)
    elif change == "run":
        snapshot.assessment_run_id = "other-run"
    else:
        snapshot.features.covenants[0].covenant_id = "other-covenant"
    with pytest.raises(ValueError):
        RiskFeatureSnapshotRepository(database).save(snapshot)


def test_sql_constraints_and_prediction_identity(records):
    database, _, _, snapshot = records
    snapshots = RiskFeatureSnapshotRepository(database)
    snapshots.save(snapshot)
    repository = RiskPredictionRepository(database)
    prediction = RiskPrediction(
        borrower_id="OTHER",
        period_end=snapshot.features.period_end,
        snapshot_id=snapshot.snapshot_id,
        model_name="stub",
        model_version="v1",
        prediction_status="stub",
    )
    with pytest.raises(ValueError, match="borrower-period"):
        repository.save(prediction)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        statement = (
            "INSERT INTO risk_predictions (prediction_id,snapshot_id,model_name,model_version,"
            "prediction_status,risk_level,breach_probability) VALUES (?,?,?,?,?,?,?)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                statement, ("p1", snapshot.snapshot_id, "test", "v1", "complete", "high", 1.1)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement, ("p2", "missing", "stub", "v1", "stub", "unknown", None))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE risk_feature_snapshots SET features_json='bad json'")


def test_factory_rejects_unknown_and_duplicate_types():
    factory = RiskModelFactory()
    with pytest.raises(ValueError, match="Unknown"):
        factory.create(RiskModelConfig(type="untrained"))
    with pytest.raises(ValueError, match="once"):
        factory.register("stub", lambda config: None)
