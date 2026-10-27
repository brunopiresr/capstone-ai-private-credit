"""Read-only snapshot selection, integrity, coverage, and replay contracts."""

import copy
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from credit_monitoring.covenants.repositories import CovenantRepository
from credit_monitoring.domain import CovenantExtraction, ExtractionResult
from credit_monitoring.evaluation.sec_snapshot import (
    capture_snapshot,
    compare_snapshot,
    content_hash,
    encoded,
    read_csv,
)


@pytest.fixture
def snapshot_inputs(tmp_path):
    database = tmp_path / "cache.sqlite3"
    catalog = tmp_path / "catalog.csv"
    catalog.write_text("document_id,source_url\nDOC,https://example.invalid/filing\n")
    (tmp_path / "DOC.md").write_text("Maximum leverage 5.00x on September 30, 2025.")
    repository = CovenantRepository(database)
    evidence = {
        "document_id": "DOC",
        "citation": "Example filing",
        "evidence_quote": "Maximum leverage 5.00x on September 30, 2025.",
    }
    repository.begin(
        "DOC",
        "old",
        metadata={},
        configuration={"prompt_version": "test"},
        total_sections=1,
        force=False,
    )
    repository.finish(
        "DOC",
        "old",
        ExtractionResult(
            prompt_version="test",
            extraction=CovenantExtraction.model_validate(
                {
                    "issuer": "Example",
                    "ticker": "EX",
                    "covenants": [
                        {
                            "covenant_name": "Leverage Ratio",
                            "covenant_type": "leverage",
                            "metric": "Leverage Ratio",
                            "operator": "<=",
                            "threshold_direction": "maximum",
                            "evidence": evidence,
                            "threshold_schedule": [
                                {
                                    "threshold": "5.00x",
                                    "period_end_dates": ["2025-09-30"],
                                    "evidence": evidence,
                                }
                            ],
                        }
                    ],
                }
            ),
        ),
    )
    return database, catalog, repository


def test_capture_and_json_replay_are_read_only(snapshot_inputs, tmp_path):
    database, catalog, _ = snapshot_inputs
    before = content_hash(database.read_bytes())
    snapshot = capture_snapshot(database, catalog, tmp_path)
    assert content_hash(database.read_bytes()) == before
    doc = snapshot["documents"]["DOC"]
    assert doc["source_sha256"] == content_hash((tmp_path / "DOC.md").read_bytes())
    assert doc["configuration"]["prompt_version"] == "test"
    report = compare_snapshot(snapshot, [])
    assert report == compare_snapshot(json.loads(encoded(snapshot)), [])
    assert not report["success"]  # An empty comparison is never a quality pass.


def test_newest_failure_does_not_fall_back_to_old_success(snapshot_inputs, tmp_path):
    database, catalog, repository = snapshot_inputs
    repository.begin("DOC", "new", metadata={}, configuration={}, total_sections=1, force=False)
    repository.fail("DOC", "new", "Interrupted")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE document_extractions SET updated_at='2026-01-01' WHERE cache_key='old'"
        )
        connection.execute(
            "UPDATE document_extractions SET updated_at='2026-01-02' WHERE cache_key='new'"
        )
    doc = capture_snapshot(database, catalog, tmp_path)["documents"]["DOC"]
    assert doc["status"] == "failed" and doc["result"] is None
    assert doc["cache_key"] == "new"


def test_missing_database_is_an_error_and_is_not_created(tmp_path):
    database = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        capture_snapshot(database, tmp_path / "catalog.csv", tmp_path)
    assert not database.exists()


def test_snapshot_tampering_is_rejected(snapshot_inputs, tmp_path):
    database, catalog, _ = snapshot_inputs
    snapshot = capture_snapshot(database, catalog, tmp_path)
    snapshot["documents"]["DOC"]["result"]["extraction"]["ticker"] = "OTHER"
    with pytest.raises(ValueError, match="checksum mismatch"):
        compare_snapshot(snapshot, [])


def test_partial_and_unsupported_are_not_full_accuracy(snapshot_inputs, tmp_path):
    database, catalog, _ = snapshot_inputs
    snapshot = capture_snapshot(database, catalog, tmp_path)
    gold = {
        "case_id": "CONTROL",
        "source_document_ids": "DOC;ABSENT",
        "ticker": "EX",
        "borrower": "Example",
        "test_date": "2025-09-30",
        "covenant_name": "Leverage Ratio",
        "covenant_type": "leverage",
        "threshold_value": "5.00",
        "operator": "<=",
        "actual_value": "",
        "headroom": "",
        "gold_status": "UNSUPPORTED",
        "unit": "x",
    }
    report = compare_snapshot(snapshot, [gold])
    assert report["success"]
    assert report["cases"][0]["status"] == "partial"
    assert report["cases"][0]["missing_source_documents"] == ["ABSENT"]
    assert report["unsupported_field_count"] == 1
    assert not report["cases"][0]["is_complete"]
    strict = compare_snapshot(snapshot, [gold], strict=True)
    assert not strict["success"]
    assert strict["cases"][0]["status"] == "failed"
    gold["source_document_ids"] = "DOC"
    complete_sources = compare_snapshot(snapshot, [gold], strict=True)
    assert complete_sources["success"]
    assert complete_sources["case_status_counts"] == {"supported_facts_match": 1}
    assert not complete_sources["cases"][0]["is_complete"]  # Unsupported target remains.
    empty = copy.deepcopy(snapshot)
    empty["documents"] = {}
    report = compare_snapshot(empty, [gold], strict=True)
    assert report["case_status_counts"] == {"unevaluable": 1}
    assert not report["success"]


def test_captured_fmc_errors_remain_visible_and_replay_without_a_database():
    root = Path(__file__).resolve().parents[3]
    fixture = root / "tests/fixtures/public_sec_snapshot"
    snapshot = json.loads((fixture / "fmc_observations.json").read_text())
    excerpts = json.loads((fixture / "fmc_source_excerpts.json").read_text())
    gold = [
        row
        for row in read_csv(root / "data/evaluation/public_sec_gold_cases.csv")
        if row["case_id"] in {"PUB_FMC_2025Q1_LEV", "PUB_FMC_2025Q1_ICR"}
    ]
    report = compare_snapshot(snapshot, gold, strict=True)
    assert report["case_status_counts"] == {"failed": 2}
    leverage, interest = report["cases"]
    assert set(map(str, leverage["checks"]["threshold_value"]["observed"])) == {"4.77", "5.25"}
    assert set(leverage["checks"]["operator"]["observed"]) == {"<", ">="}
    assert list(map(str, interest["checks"]["threshold_value"]["observed"])) == ["3.84"]
    assert encoded(report) == encoded(
        compare_snapshot(json.loads(encoded(snapshot)), gold, strict=True)
    )
    # Independently inspected source excerpts establish the limits and actuals;
    # these assertions do not create or repair any model observation.
    quarterly = next(item["text"] for item in excerpts if item["document_id"] == "DOC_FMC_Q1_2025")
    assert "was 4.77, which is below the maximum leverage of 5.25" in quarterly
    assert "was 3.84, which is above the minimum interest coverage of 3.00" in quarterly
    amendment = snapshot["documents"]["DOC_FMC_AMD3_2025"]["result"]["extraction"]
    assert "Interest Coverage Ratio" in amendment["covenants"][0]["evidence"]["evidence_quote"]
    assert amendment["covenants"][0]["covenant_name"] == "Maximum Leverage Ratio"
    # The source itself repeats the leverage header under the interest clause.
    # Preserve that discrepancy, rather than silently repairing the evidence.
    schedule = (root / "tests/fixtures/sec_covenant_v2/fmc_amendment_schedule.md").read_text()
    interest_clause = schedule.split("Minimum Interest Coverage Ratio.", 1)[1]
    assert "not less than 3.50 to 1.00" in interest_clause
    assert "Fiscal Quarter | | | Maximum Leverage Ratio" in interest_clause


def test_cli_replays_failures_and_refuses_to_overwrite_inputs(tmp_path):
    root = Path(__file__).resolve().parents[3]
    snapshot = tmp_path / "observations.json"
    snapshot.write_bytes(
        (root / "tests/fixtures/public_sec_snapshot/fmc_observations.json").read_bytes()
    )
    before = snapshot.read_bytes()
    command = [
        sys.executable,
        str(root / "scripts/compare_public_sec_gold.py"),
        "--snapshot",
        str(snapshot),
        "--require-complete-sources",
    ]
    for name in ("first", "replay"):
        completed = subprocess.run(
            command + ["--output", str(tmp_path / name)], capture_output=True, text=True
        )
        assert completed.returncode == 1, completed.stderr
    assert (tmp_path / "first/report.json").read_bytes() == (
        tmp_path / "replay/report.json"
    ).read_bytes()
    manifest = json.loads((tmp_path / "first/manifest.json").read_text())
    assert manifest["manifest_version"] == 1 and manifest["comparison_code_sha256"]
    rejected = subprocess.run(command + ["--output", str(tmp_path)], capture_output=True, text=True)
    assert rejected.returncode == 2 and "must not overwrite" in rejected.stderr
    assert snapshot.read_bytes() == before
