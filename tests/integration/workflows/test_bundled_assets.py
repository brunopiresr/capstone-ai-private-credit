"""A checkout can assess and predict using bundled assets without import or training."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date

import pytest

from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.ml.artifacts import file_hash
from credit_monitoring.paths import APP_SYNTHETIC_DIR, BUNDLED_FINANCIAL_DB, MODELS_DIR, ROOT
from credit_monitoring.web.workspace import SyntheticWorkspace


def test_bundled_database_matches_authored_csv(tmp_path):
    imported = tmp_path / "imported.sqlite3"
    load_financials(APP_SYNTHETIC_DIR / "synthetic_quarterly_financials.csv", imported)

    def rows(database):
        with sqlite3.connect(database) as connection:
            connection.row_factory = sqlite3.Row
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            return [
                {key: row[key] for key in row.keys() if key not in {"source_file", "loaded_at"}}
                for row in connection.execute(
                    "SELECT * FROM quarterly_financials ORDER BY borrower_id, period_end"
                )
            ]

    assert rows(BUNDLED_FINANCIAL_DB) == rows(imported)
    with sqlite3.connect(BUNDLED_FINANCIAL_DB) as connection:
        sources = connection.execute("SELECT DISTINCT source_file FROM quarterly_financials")
        assert sources.fetchall() == [("data/app/synthetic/synthetic_quarterly_financials.csv",)]


@pytest.mark.parametrize("mode", ["Off", "Logistic Regression"])
def test_relocated_workspace_uses_only_bundled_app_inputs_and_model(tmp_path, monkeypatch, mode):
    if mode == "Logistic Regression":
        pytest.importorskip("sklearn")
    data = tmp_path / "checkout" / "data"
    shutil.copytree(APP_SYNTHETIC_DIR, data / "app" / "synthetic")
    shutil.copytree(MODELS_DIR, data / "models")

    def forbidden_import(*args, **kwargs):
        raise AssertionError("A new user must not need to import data.")

    monkeypatch.setattr(
        "credit_monitoring.ingestion.loaders.financials.load_financials", forbidden_import
    )
    workspace = SyntheticWorkspace(data, tmp_path / "runtime")
    before = file_hash(data / "app" / "synthetic" / "financials.sqlite3")
    period = date(2025, 9, 30)
    assessment = workspace.assessment_service(mode).assess(
        "SYN002", period, period, ml_enabled=mode != "Off"
    )
    assert assessment.results[0].actual_value == pytest.approx(135 / 26)
    assert assessment.ml_status == ("disabled" if mode == "Off" else "complete")
    if mode != "Off":
        assert 0 <= assessment.prediction.breach_probability <= 1
    assert file_hash(data / "app" / "synthetic" / "financials.sqlite3") == before


def test_cli_defaults_to_bundled_database_without_import(tmp_path):
    before = file_hash(BUNDLED_FINANCIAL_DB)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_assessment.py"),
            "--borrower-id",
            "SYN002",
            "--period-end",
            "2025-09-30",
            "--information-cutoff",
            "2025-09-30",
            "--analytics-db",
            str(tmp_path / "analytics.sqlite3"),
        ],
        cwd=tmp_path,
        env={**os.environ, "LOGFIRE_SEND_TO_LOGFIRE": "false"},
        capture_output=True,
        text=True,
        check=True,
    )
    assessment = json.loads(completed.stdout)
    assert assessment["results"][0]["actual_value"] == pytest.approx(135 / 26)
    assert file_hash(BUNDLED_FINANCIAL_DB) == before
