"""Exercise real SQLite assessments using existing inputs and independent gold expectations."""

import csv
import json
import logging
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.calculations.leverage import divide
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.ml.factory import RiskModelFactory

DATA = Path(__file__).resolve().parents[3] / "data"
with (DATA / "synthetic_gold_labels.csv").open(newline="") as source:
    GOLD_CASES = list(csv.DictReader(source))


@pytest.fixture
def assessment_service(tmp_path):
    """Use isolated databases without changing the repository's processed data."""
    financial_database = tmp_path / "financials.sqlite3"
    load_financials(DATA / "synthetic_quarterly_financials.csv", financial_database)
    return AssessmentService(
        financial_repository=FinancialRepository(financial_database),
        covenant_reader=SyntheticCovenantReader(DATA / "synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(analytics_database=tmp_path / "analytics.sqlite3"),
    )


@pytest.mark.parametrize("gold", GOLD_CASES, ids=lambda row: row["case_id"])
def test_existing_synthetic_cases(assessment_service, gold):
    period = date.fromisoformat(gold["period_end"])
    assessment = assessment_service.assess(gold["borrower_id"], period, period)
    assert assessment.verification.is_valid
    assert assessment.ml_status == "disabled"
    assert assessment.prediction is None
    result = assessment.results[0]
    if gold["borrower_id"] == "SYN010":
        assert result.compliance_status == (
            "not_tested" if period == date(2025, 6, 30) else "incomplete"
        )
        assert result.actual_value is None
        assert result.headroom is None
        return
    expected_status = {
        "COMPLIANT": "compliant",
        "COMPLIANT_EARLY_WARNING": "compliant",
        "BREACH": "breach",
        "WAIVED": "waived",
        "DATA_CONFLICT_ABSTAIN": "incomplete",
    }[gold["expected_status"]]
    assert result.compliance_status == expected_status
    if gold["expected_metric"]:
        assert result.actual_value == pytest.approx(float(gold["expected_metric"]), abs=0.00005)
    else:
        assert result.actual_value is None
    if gold["expected_headroom"]:
        assert result.headroom == pytest.approx(float(gold["expected_headroom"]), abs=0.00005)
    else:
        assert result.headroom is None
    if gold["expected_evidence_issue"]:
        assert any(gold["expected_evidence_issue"] in issue for issue in result.issues)


def test_stub_receives_stored_history_and_round_trips(assessment_service):
    period = date(2025, 9, 30)
    assessment = assessment_service.assess("SYN002", period, period, ml_enabled=True)
    assert assessment.ml_status == "stub"
    assert len(assessment.history) == 2
    features = assessment.feature_snapshot.features
    assert features.covenants[0].metric_change_qoq == pytest.approx(135 / 26 - 130 / 28)
    assert features.covenants[0].headroom_change_qoq < 0
    assert features.reported_ebitda_growth_qoq == pytest.approx(-2 / 28)
    assert features.reported_ebitda_growth_yoy is None
    assert not features.information_availability_known
    assert assessment.prediction.breach_probability is None
    assert assessment.prediction.risk_level == "unknown"
    assert (
        assessment_service.snapshot_repository.get(
            assessment.feature_snapshot.snapshot_id,
        )
        == assessment.feature_snapshot
    )
    assert (
        assessment_service.prediction_repository.get(
            assessment.prediction.prediction_id,
        )
        == assessment.prediction
    )
    assert all(result.period_end <= period for result in assessment.history)
    assert "Subsequent breach" not in assessment.model_dump_json()
    assert "expected_metric" not in assessment.model_dump_json()


def test_inputs_and_snapshot_survive_reload(assessment_service, tmp_path):
    period = date(2025, 9, 30)
    first = assessment_service.assess("SYN002", period, period, ml_enabled=True)
    snapshot = first.feature_snapshot
    updated = tmp_path / "updated.csv"
    updated.write_text(
        "borrower_id,period_end,total_debt,cash,reported_ebitda,eligible_addbacks\n"
        "SYN002,2025-09-30,140,10,30,0\n",
    )
    load_financials(updated, assessment_service.financial_repository.database_path)
    second = assessment_service.assess("SYN002", period, period, ml_enabled=True)
    assert first.assessment_run_id != second.assessment_run_id
    assert first.results[0].actual_value != second.results[0].actual_value
    assert assessment_service.snapshot_repository.get(snapshot.snapshot_id) == snapshot
    old_results = assessment_service.result_repository.get_history(
        "SYN002",
        period_end=period,
        information_cutoff=period,
        assessment_run_id=first.assessment_run_id,
    )
    assert old_results[-1].financial_inputs["financial_period"]["metrics"]["reported_ebitda"] == 26
    with sqlite3.connect(assessment_service.result_repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM covenant_results").fetchone()[0] == 6


def test_no_nearest_period_substitution(assessment_service):
    with sqlite3.connect(assessment_service.financial_repository.database_path) as connection:
        connection.execute(
            "DELETE FROM quarterly_financials WHERE borrower_id=? AND period_end=?",
            ("SYN002", "2025-06-30"),
        )
    period = date(2025, 9, 30)
    features = assessment_service.assess(
        "SYN002", period, period, ml_enabled=True
    ).feature_snapshot.features
    assert features.covenants[0].metric_change_qoq is None
    assert features.covenants[0].previous_breach is None
    assert features.reported_ebitda_growth_qoq is None


@pytest.mark.parametrize("failure", ["exception", "invalid", "identity", "snapshot", "prediction"])
def test_ml_failures_preserve_compliance(assessment_service, monkeypatch, failure):
    class TestModel:
        def predict(self, features):
            if failure == "exception":
                raise RuntimeError("Model unavailable")
            if failure == "invalid":
                return RiskPrediction.model_construct(
                    borrower_id=features.borrower_id,
                    period_end=features.period_end,
                    model_name="test",
                    model_version="v1",
                    prediction_status="complete",
                    breach_probability=1.2,
                )
            return RiskPrediction(
                borrower_id="OTHER" if failure == "identity" else features.borrower_id,
                period_end=features.period_end,
                model_name="test",
                model_version="v1",
                prediction_status="complete",
                breach_probability=0.4,
            )

    factory = RiskModelFactory()
    factory.register("test", lambda config: TestModel())
    assessment_service.model_factory = factory
    assessment_service.settings.risk_model = RiskModelConfig(type="test")

    def storage_failure(record):
        raise sqlite3.OperationalError("Storage unavailable")

    if failure == "snapshot":
        monkeypatch.setattr(assessment_service.snapshot_repository, "save", storage_failure)
    if failure == "prediction":
        monkeypatch.setattr(assessment_service.prediction_repository, "save", storage_failure)
    period = date(2025, 9, 30)
    assessment = assessment_service.assess("SYN002", period, period, ml_enabled=True)
    assert assessment.ml_status == "failed"
    assert assessment.results[0].compliance_status == "compliant"
    assert assessment.verification.is_valid
    assert assessment.issues
    assert (
        len(
            assessment_service.result_repository.get_history(
                "SYN002",
                period_end=period,
                information_cutoff=period,
                assessment_run_id=assessment.assessment_run_id,
            )
        )
        == 3
    )


def test_registered_model_and_narrator_receive_typed_context(assessment_service):
    class TestModel:
        def predict(self, features):
            features.covenants.clear()
            return RiskPrediction(
                borrower_id=features.borrower_id,
                period_end=features.period_end,
                model_name="baseline",
                model_version="test-v1",
                prediction_status="complete",
                breach_probability=0.41,
                risk_level="medium",
                top_drivers=["Declining headroom"],
            )

    class Narrator:
        def summarize(self, context):
            assert context["ml_prediction"]["breach_probability"] == 0.41
            assert context["risk_features"]["covenants"]
            assert context["evidence"]
            assert "notes" not in json.dumps(context)
            context["current_financials"][0]["financial_period"]["metrics"]["total_debt"] = 999
            return "The model predicts a 41% breach probability; current compliance is unchanged."

    factory = RiskModelFactory()
    factory.register("baseline", lambda config: TestModel())
    assessment_service.model_factory = factory
    assessment_service.settings.risk_model = RiskModelConfig(type="baseline")
    assessment_service.risk_analysis_service.narrator = Narrator()
    period = date(2025, 9, 30)
    assessment = assessment_service.assess("SYN002", period, period, ml_enabled=True)
    assert assessment.ml_status == "complete"
    assert assessment.verification.is_valid
    assert (
        assessment.results[0].financial_inputs["financial_period"]["metrics"]["total_debt"] == 145
    )
    assert assessment.feature_snapshot.features.covenants


def test_missing_borrower_and_invalid_cutoff(assessment_service):
    period = date(2025, 9, 30)
    assessment = assessment_service.assess("UNKNOWN", period, period, ml_enabled=True)
    assert not assessment.results and assessment.ml_status == "unavailable"
    with pytest.raises(ValueError, match="cutoff"):
        assessment_service.assess("SYN001", period, date(2025, 8, 30))


def test_prediction_bounds_and_finite_inputs():
    with pytest.raises(ValidationError):
        RiskPrediction(
            borrower_id="SYN001",
            period_end=date(2025, 9, 30),
            model_name="test",
            model_version="v1",
            prediction_status="complete",
            breach_probability=float("inf"),
        )


def test_logs_link_resolution_calculations_and_trends_to_each_run(assessment_service, caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    period = date(2025, 9, 30)
    for borrower in ("SYN002", "SYN006"):
        caplog.clear()
        assessment = assessment_service.assess(borrower, period, period, ml_enabled=True)
        records = [r for r in caplog.records if hasattr(r, "operation")]
        assert records
        assert all(r.assessment_run_id == assessment.assessment_run_id for r in records)
        assert all(r.borrower_id == borrower for r in records)
        expected_periods = {
            result.period_end.isoformat() for result in assessment.results + assessment.history
        }
        assert {r.period_end for r in records} == expected_periods
        trends = [r for r in records if r.operation == "difference"]
        if borrower == "SYN002":
            assert trends and all(r.covenant_id for r in trends)
    divide(10, 2)
    assert not hasattr(caplog.records[-1], "assessment_run_id")


@pytest.mark.parametrize("level", [None, "INFO", "WARNING"])
def test_cli_logging_keeps_stdout_json_and_is_opt_in(assessment_service, tmp_path, level):
    command = [
        sys.executable,
        str(DATA.parent / "scripts/run_assessment.py"),
        "--borrower-id",
        "SYN006",
        "--period-end",
        "2025-09-30",
        "--information-cutoff",
        "2025-09-30",
        "--financial-db",
        str(assessment_service.financial_repository.database_path),
        "--analytics-db",
        str(tmp_path / "cli-analytics.sqlite3"),
    ]
    if level:
        command.extend(["--log-level", level])
    outcome = subprocess.run(command, capture_output=True, text=True, check=True)
    assessment = json.loads(outcome.stdout)
    assert assessment["results"][0]["actual_value"] is not None
    if level == "INFO":
        assert "apply_addback_cap complete" in outcome.stderr
        assert '"borrower_id": "SYN006"' in outcome.stderr
        assert "calculate_covenant complete" in outcome.stderr
    else:
        assert outcome.stderr == ""
