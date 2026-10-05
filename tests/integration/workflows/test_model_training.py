"""Verify generation, leakage boundaries, saved pipelines, and runtime persistence."""

import csv
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import CovenantResult
from credit_monitoring.domain.risk_features import BorrowerRiskFeatures, CovenantRiskFeatures
from credit_monitoring.features.model_features import FEATURE_COLUMNS, model_feature_row
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.ml.artifacts import file_hash, write_json
from credit_monitoring.ml.synthetic_dataset import generate_dataset, outcome_label

DATA = Path(__file__).resolve().parents[3] / "data"


def _csv_rows(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def _jsonl_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture(scope="module")
def generated_dataset(tmp_path_factory):
    """Generate a small but representative dataset once for the integration checks."""
    directory = tmp_path_factory.mktemp("training-data")
    generate_dataset(DATA, directory, borrowers_per_scenario=5)
    return directory


@pytest.fixture(scope="module")
def trained_artifact(generated_dataset, tmp_path_factory):
    """Train an actual baseline while allowing core-only installs to skip ML tests."""
    pytest.importorskip("sklearn")
    from credit_monitoring.ml.training import train_model

    directory = tmp_path_factory.mktemp("trained-artifact")
    train_model(generated_dataset, directory)
    return directory


def test_dataset_is_reproducible_and_preserves_fixtures(generated_dataset, tmp_path):
    fixture_hashes = {path.name: file_hash(path) for path in DATA.glob("synthetic_*.csv")}
    manifest = generate_dataset(DATA, tmp_path, borrowers_per_scenario=5)
    assert manifest["borrower_count"] == 60
    assert manifest["observation_count"] == 480
    assert len(manifest["scenario_counts"]) == 12
    for path in generated_dataset.iterdir():
        assert path.read_bytes() == (tmp_path / path.name).read_bytes()
    assert fixture_hashes == {path.name: file_hash(path) for path in DATA.glob("synthetic_*.csv")}
    with pytest.raises(ValueError, match="separate"):
        generate_dataset(DATA, DATA, borrowers_per_scenario=5)


def test_labels_follow_future_calculations_and_unknowns_are_excluded(generated_dataset):
    calculations = {
        row["result_id"]: CovenantResult.model_validate(row)
        for row in _jsonl_rows(generated_dataset / "calculations.jsonl")
    }
    rows = {row["sample_id"]: row for row in _csv_rows(generated_dataset / "training.csv")}
    observed = set()
    for outcome in _jsonl_rows(generated_dataset / "outcomes.jsonl"):
        results = [calculations[result_id] for result_id in outcome["source_result_ids"]]
        assert (outcome["target"], outcome["reason"]) == outcome_label(results)
        observed.add(outcome["reason"])
        if outcome["target"] is None:
            assert rows[outcome["sample_id"]]["split"] == "unused"
            assert rows[outcome["sample_id"]]["target"] == ""
        if results:
            current_date = outcome["sample_id"].split(":")[-1]
            assert all(result.period_end.isoformat() > current_date for result in results)
    assert {
        "observed_breach",
        "observed_no_breach",
        "future_outcome_missing",
        "future_outcome_unresolved",
        "no_active_future_test",
    } <= observed


def test_partitions_separate_borrowers_and_outcome_time(generated_dataset):
    rows = _csv_rows(generated_dataset / "training.csv")
    partitions = {
        name: [row for row in rows if row["split"] == name]
        for name in ("train", "validation", "test")
    }
    borrower_sets = {
        name: {row["borrower_id"] for row in records} for name, records in partitions.items()
    }
    assert not borrower_sets["train"] & borrower_sets["validation"]
    assert not borrower_sets["train"] & borrower_sets["test"]
    assert not borrower_sets["validation"] & borrower_sets["test"]
    assert max(row["period_end"] for row in partitions["train"]) <= "2025-09-30"
    assert {row["period_end"] for row in partitions["validation"]} <= {"2026-03-31", "2026-06-30"}
    assert {row["period_end"] for row in partitions["test"]} == {"2026-09-30"}
    for row in rows:
        if row["period_end"] == "2026-12-31":
            assert row["target"] == "" and row["split"] == "unused"


def test_contractual_edges_remain_present(generated_dataset):
    results = [
        CovenantResult.model_validate(row)
        for row in _jsonl_rows(generated_dataset / "calculations.jsonl")
    ]
    amended = [result for result in results if "SIM_SYN004" in result.borrower_id]
    assert all(
        result.threshold == (4.75 if result.period_end <= date(2025, 6, 30) else 5.5)
        for result in amended
    )
    holiday = [result for result in results if "SIM_SYN005" in result.borrower_id]
    assert all(
        result.compliance_status == "waived"
        for result in holiday
        if result.period_end in (date(2025, 6, 30), date(2025, 9, 30))
    )
    springing = [result for result in results if "SIM_SYN010" in result.borrower_id]
    assert any(result.actual_value is not None for result in springing)
    assert any("DEBT_SOURCE_CONFLICT" in " ".join(result.issues) for result in results)
    assert any(result.compliance_status == "incomplete" for result in results)
    assert any(result.resolved_covenant.addback_cap_fraction == 0.2 for result in results)
    assert any(result.resolved_covenant.cash_netting_cap == 25 for result in results)
    assert any(result.resolved_covenant.synergy_cap_fraction == 0.5 for result in results)


def test_future_financial_changes_cannot_change_earlier_features(
    generated_dataset, tmp_path, monkeypatch
):
    from credit_monitoring.ml import synthetic_dataset

    original_simulator = synthetic_dataset._simulate_history

    def change_future(*arguments):
        rows = original_simulator(*arguments)
        for row in rows:
            if row["period_end"] >= "2026-01-01":
                row["reported_ebitda"] = 1.0
                row["total_debt"] = 900.0
        return rows

    monkeypatch.setattr(synthetic_dataset, "_simulate_history", change_future)
    generate_dataset(DATA, tmp_path, borrowers_per_scenario=5)
    before = {
        row["sample_id"]: row["features"]
        for row in _jsonl_rows(generated_dataset / "features.jsonl")
    }
    after = {row["sample_id"]: row["features"] for row in _jsonl_rows(tmp_path / "features.jsonl")}
    for sample_id in before:
        if sample_id.split(":")[-1] <= "2025-12-31":
            assert before[sample_id] == after[sample_id]
    assert any(before[sample_id] != after[sample_id] for sample_id in before)


def test_training_runtime_conversion_matches_and_aggregates_covenants(generated_dataset):
    rows = {row["sample_id"]: row for row in _csv_rows(generated_dataset / "training.csv")}
    for record in _jsonl_rows(generated_dataset / "features.jsonl"):
        features = BorrowerRiskFeatures.model_validate(record["features"])
        encoded = model_feature_row(features)
        assert tuple(encoded) == FEATURE_COLUMNS
        for column, value in encoded.items():
            stored = rows[record["sample_id"]][column]
            assert value == (float(stored) if stored else None)
    covenant = CovenantRiskFeatures(
        covenant_id="first",
        covenant_type="total_leverage",
        actual_value=4.0,
        threshold=5.0,
        headroom=1.0,
        compliance_status="compliant",
    )
    features = BorrowerRiskFeatures(
        borrower_id="ignored",
        period_end="2025-03-31",
        information_cutoff="2025-03-31",
        covenants=[
            covenant,
            covenant.model_copy(
                update={"covenant_id": "second", "actual_value": 6.0, "headroom": -1.0}
            ),
        ],
    )
    row = model_feature_row(features)
    assert row["total_leverage__mean_actual_value"] == 5.0
    assert row["total_leverage__min_normalized_headroom"] == -0.2
    assert row["total_leverage__covenant_count"] == 2
    assert not any("borrower_id" in column or "scenario" in column for column in row)


def test_saved_model_matches_offline_predictions_and_abstains(generated_dataset, trained_artifact):
    import joblib
    import pandas as pd

    from credit_monitoring.ml.logistic_model import LogisticRegressionRiskModel

    model = LogisticRegressionRiskModel(
        RiskModelConfig(type="logistic_regression", artifact_path=trained_artifact)
    )
    pipeline = joblib.load(trained_artifact / "pipeline.joblib")
    for record in _jsonl_rows(generated_dataset / "features.jsonl")[:16]:
        features = BorrowerRiskFeatures.model_validate(record["features"])
        prediction = model.predict(features)
        if prediction.prediction_status == "complete":
            frame = pd.DataFrame([model_feature_row(features)], columns=FEATURE_COLUMNS).astype(
                float
            )
            assert prediction.breach_probability == pipeline.predict_proba(frame)[0, 1]
            assert prediction.risk_level == "unknown"
            assert prediction.anomaly_score is None
            assert prediction.model_artifact_hash == file_hash(trained_artifact / "pipeline.joblib")
    empty = BorrowerRiskFeatures(
        borrower_id="unknown", period_end="2025-03-31", information_cutoff="2025-03-31"
    )
    assert model.predict(empty).prediction_status == "unavailable"
    assert model.predict(empty).breach_probability is None


def test_held_out_values_do_not_change_fitted_pipeline(
    generated_dataset, trained_artifact, tmp_path
):
    import joblib
    import numpy as np
    import pandas as pd

    from credit_monitoring.ml.training import train_model

    dataset = tmp_path / "dataset"
    shutil.copytree(generated_dataset, dataset)
    frame = pd.read_csv(dataset / "training.csv")
    for column in ("total_debt_growth_qoq", "total_leverage__mean_actual_value"):
        frame.loc[frame["split"] != "train", column] = 10000
    frame.to_csv(dataset / "training.csv", index=False)
    _refresh_training_hash(dataset)
    artifact = tmp_path / "artifact"
    train_model(dataset, artifact)
    before = joblib.load(trained_artifact / "pipeline.joblib")
    after = joblib.load(artifact / "pipeline.joblib")
    np.testing.assert_array_equal(before["imputer"].statistics_, after["imputer"].statistics_)
    np.testing.assert_array_equal(before["scaler"].mean_, after["scaler"].mean_)
    np.testing.assert_array_equal(before["classifier"].coef_, after["classifier"].coef_)


def _refresh_training_hash(dataset):
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_hashes"]["training.csv"] = file_hash(dataset / "training.csv")
    write_json(manifest_path, manifest)


@pytest.mark.parametrize("problem", ["checksum", "version", "schema", "dependency", "target"])
def test_incompatible_artifacts_are_rejected(trained_artifact, tmp_path, problem):
    from credit_monitoring.ml.logistic_model import LogisticRegressionRiskModel

    shutil.copytree(trained_artifact, tmp_path / "artifact")
    directory = tmp_path / "artifact"
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if problem == "checksum":
        with (directory / "pipeline.joblib").open("ab") as destination:
            destination.write(b"changed")
    elif problem == "version":
        manifest["model_version"] = "other"
    elif problem == "schema":
        manifest["feature_columns"] = []
    elif problem == "dependency":
        manifest["dependency_versions"]["scikit-learn"] = "0.0"
    else:
        manifest["prediction_target"] = "other"
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError):
        LogisticRegressionRiskModel(
            RiskModelConfig(type="logistic_regression", artifact_path=directory)
        )


def test_runtime_prediction_is_persisted_and_failures_preserve_compliance(
    generated_dataset, trained_artifact, tmp_path
):
    financial_database = tmp_path / "financials.sqlite3"
    load_financials(generated_dataset / "quarterly_financials.csv", financial_database)
    service = AssessmentService(
        financial_repository=FinancialRepository(financial_database),
        covenant_reader=SyntheticCovenantReader(generated_dataset / "covenant_terms.csv"),
        settings=AssessmentSettings(
            analytics_database=tmp_path / "analytics.sqlite3",
            risk_model=RiskModelConfig(type="logistic_regression", artifact_path=trained_artifact),
        ),
    )
    period = date(2026, 9, 30)
    assessment = service.assess("SIM_SYN001_0001", period, period, ml_enabled=True)
    assert assessment.ml_status == "complete"
    assert assessment.verification.is_valid
    assert 0 <= assessment.prediction.breach_probability <= 1
    assert "synthetic" in assessment.narrative
    assert (
        service.prediction_repository.get(assessment.prediction.prediction_id)
        == assessment.prediction
    )
    assert (
        service.snapshot_repository.get(assessment.feature_snapshot.snapshot_id)
        == assessment.feature_snapshot
    )
    assert service.assess("SIM_SYN001_0001", period, period).ml_status == "disabled"
    service.settings.risk_model.artifact_path = tmp_path / "missing"
    failed = service.assess("SIM_SYN001_0001", period, period, ml_enabled=True)
    assert failed.ml_status == "failed"
    assert failed.results[0].compliance_status == assessment.results[0].compliance_status
    assert failed.prediction.prediction_status == "failed"
    assert service.prediction_repository.get(failed.prediction.prediction_id) == failed.prediction


def test_training_rejects_missing_classes(generated_dataset, tmp_path):
    pytest.importorskip("sklearn")
    import pandas as pd

    from credit_monitoring.ml.training import train_model

    dataset = tmp_path / "dataset"
    shutil.copytree(generated_dataset, dataset)
    frame = pd.read_csv(dataset / "training.csv")
    frame.loc[frame["split"] == "train", "target"] = 0
    frame.to_csv(dataset / "training.csv", index=False)
    _refresh_training_hash(dataset)
    with pytest.raises(ValueError, match="breaches and non-breaches"):
        train_model(dataset, tmp_path / "artifact")
    assert not (tmp_path / "artifact").exists()
