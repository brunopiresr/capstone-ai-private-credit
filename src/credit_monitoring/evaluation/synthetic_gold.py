"""Evaluation-only adapter; never used to construct working assessments."""

import csv
from pathlib import Path


def load_synthetic_gold(directory: Path) -> list[dict[str, str]]:
    with (directory / "synthetic_gold_labels.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    expansion = directory / "synthetic_bundle_gold_cases.csv"
    if expansion.exists():
        with expansion.open(newline="") as source:
            for row in csv.DictReader(source):
                rows.append(
                    {
                        **row,
                        "case_id": row["gold_case_id"],
                        "covenant_id": row["covenant_id"].removeprefix(row["borrower_id"] + "-"),
                        "expected_metric": row["expected_ratio"],
                        "expected_headroom": row["headroom_ratio_points"],
                        "expected_status": {
                            "PASS": "COMPLIANT",
                            "INDETERMINATE": "INCOMPLETE",
                            "UNKNOWN_TRIGGER": "UNRESOLVED",
                        }.get(row["expected_status"], row["expected_status"]),
                        "early_warning_expected": "",
                        "expected_evidence_issue": "",
                        "rationale": row["calculation_explanation"],
                    }
                )
    return rows
