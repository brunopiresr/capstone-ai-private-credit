"""Generate simulated histories from PoC templates without changing benchmark fixtures."""

import csv
import json
import random
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.assessment import CovenantResult, FinancialPeriod
from credit_monitoring.features.model_features import (
    FEATURE_COLUMNS,
    MODEL_FEATURE_SCHEMA_VERSION,
    has_usable_current_inputs,
    model_feature_row,
)
from credit_monitoring.features.risk_feature_builder import RiskFeatureBuilder
from credit_monitoring.financials.mappings import FINANCIAL_METRICS
from credit_monitoring.persistence.analytics_repositories import CovenantResultRepository

from .artifacts import file_hash, write_json

GENERATOR_VERSION = "v1"
QUARTERS = tuple(
    date(year, month, day)
    for year in (2025, 2026)
    for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
)
INPUT_FILES = (
    "synthetic_borrowers.csv",
    "synthetic_covenant_terms.csv",
    "synthetic_quarterly_financials.csv",
)
DEFAULT_METRICS = {
    "total_debt": 120.0,
    "cash": 10.0,
    "reported_ebitda": 30.0,
    "eligible_addbacks": 0.0,
    "cash_interest": 8.0,
    "capex": 5.0,
    "cash_taxes": 2.0,
    "scheduled_principal": 4.0,
    "rent": 6.0,
    "revolver_availability_pct": 40.0,
    "acquired_ebitda": 0.0,
    "synergy_addback": 0.0,
}
SCENARIO_DRIFT = {
    "healthy": 0.015,
    "declining_headroom": -0.035,
    "outright_breach": -0.005,
    "amendment_precedence": -0.01,
    "covenant_holiday": -0.01,
    "addback_cap": -0.01,
    "conflicting_data": 0.0,
    "coverage_breach": -0.01,
    "fccr_early_warning": -0.025,
    "springing_covenant": -0.015,
    "cash_netting_cap": -0.01,
    "pro_forma_acquisition": 0.0,
}


def _read_csv(path: Path) -> list[dict]:
    """Read source records without importing them into application storage."""
    with path.open(newline="", encoding="utf-8-sig") as source:
        return list(csv.DictReader(source))


def _write_csv(path: Path, rows: list[dict], columns: list[str] | tuple[str, ...]) -> None:
    """Write explicit columns, retaining absent financial inputs as blank cells."""
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write reproducible records without nonfinite numeric values."""
    with path.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def outcome_label(results: list[CovenantResult]) -> tuple[int | None, str]:
    """Treat uncertainty and wholly inactive tests as unknown, never negative labels."""
    if any(result.compliance_status == "breach" for result in results):
        return 1, "observed_breach"
    if not results:
        return None, "future_outcome_missing"
    if any(
        result.compliance_status not in ("compliant", "waived", "not_tested") for result in results
    ):
        return None, "future_outcome_unresolved"
    if any(result.compliance_status == "compliant" for result in results):
        return 0, "observed_no_breach"
    return None, "no_active_future_test"


def evaluation_split(role: str, period: date, label: int | None) -> str:
    """Separate borrowers and prevent training outcomes from reaching validation time."""
    if label is None:
        return "unused"
    if role == "train" and period <= date(2025, 9, 30):
        return "train"
    if role == "validation" and period in (date(2026, 3, 31), date(2026, 6, 30)):
        return "validation"
    if role == "test" and period == date(2026, 9, 30):
        return "test"
    return "unused"


def _simulate_history(
    borrower_id: str, scenario: str, template: dict, random_source: random.Random
) -> list[dict]:
    """Simulate correlated financial paths, including recoveries and unreconciled inputs."""
    scale = random_source.uniform(0.6, 1.7)
    metrics = {}
    for name, default in DEFAULT_METRICS.items():
        value = float(template[name]) if template.get(name) else default
        metrics[name] = value if name == "revolver_availability_pct" else value * scale
    metrics["reported_ebitda"] *= random_source.uniform(0.78, 1.25)
    metrics["total_debt"] *= random_source.uniform(0.85, 1.15)
    drift = SCENARIO_DRIFT[scenario] + random_source.uniform(-0.035, 0.035)
    recovery = random_source.random() < 0.35
    rows = []
    for quarter_index, period in enumerate(QUARTERS):
        if quarter_index:
            current_drift = abs(drift) if recovery and quarter_index >= 4 else drift
            shock = random_source.uniform(-0.16, 0.12) if random_source.random() < 0.12 else 0
            metrics["reported_ebitda"] *= max(
                0.5, 1 + current_drift + random_source.gauss(0, 0.035) + shock
            )
            metrics["total_debt"] *= max(
                0.5, 1 - current_drift * 0.4 + random_source.gauss(0, 0.025)
            )
            metrics["cash"] *= max(0.5, 1 + current_drift + random_source.gauss(0, 0.06))
            for name in ("cash_interest", "capex", "cash_taxes", "scheduled_principal", "rent"):
                metrics[name] *= max(0.5, 1 + random_source.gauss(0.005, 0.025))
        metrics["revolver_availability_pct"] = min(
            100, max(0, metrics["revolver_availability_pct"] + random_source.gauss(-2, 5))
        )
        row = {name: round(value, 6) for name, value in metrics.items()}
        if scenario == "conflicting_data" and random_source.random() < 0.55:
            row["financials_debt"] = row["total_debt"]
            row["compliance_certificate_debt"] = round(row["total_debt"] * 1.1, 6)
        else:
            row["financials_debt"] = None
            row["compliance_certificate_debt"] = None
        if random_source.random() < 0.03:
            row["reported_ebitda"] = None
        row.update(borrower_id=borrower_id, period_end=period.isoformat())
        rows.append(row)
    return rows


def generate_dataset(
    source_directory: Path,
    output_directory: Path,
    *,
    seed: int = 42,
    borrowers_per_scenario: int = 50,
) -> dict:
    """Write reproducible training files using existing calculation and feature services.

    Monetary defaults and completed inputs are simulation assumptions, not reconstructed
    benchmark facts. Gold labels and financial notes are never used to generate features.
    """
    if borrowers_per_scenario < 5:
        raise ValueError("At least five borrowers per scenario are required for three partitions.")
    source_directory = source_directory.resolve()
    output_directory = output_directory.resolve()
    if output_directory == source_directory or source_directory.is_relative_to(output_directory):
        raise ValueError("Generated outputs must be separate from the source fixtures.")
    output_directory.mkdir(parents=True, exist_ok=True)
    sources = {name: _read_csv(source_directory / name) for name in INPUT_FILES}
    random_source = random.Random(seed)
    borrowers, financials, terms = [], [], []
    for template in sources[INPUT_FILES[0]]:
        template_id = template["borrower_id"]
        base = next(row for row in sources[INPUT_FILES[2]] if row["borrower_id"] == template_id)
        roles = ["train"] * int(borrowers_per_scenario * 0.7) + ["validation"] * max(
            1, int(borrowers_per_scenario * 0.14)
        )
        roles.extend(["test"] * (borrowers_per_scenario - len(roles)))
        random_source.shuffle(roles)
        for borrower_index, role in enumerate(roles, start=1):
            borrower_id = f"SIM_{template_id}_{borrower_index:04d}"
            borrowers.append(
                {
                    "borrower_id": borrower_id,
                    "template_id": template_id,
                    "scenario": template["scenario"],
                    "partition_role": role,
                }
            )
            financials.extend(
                _simulate_history(borrower_id, template["scenario"], base, random_source)
            )
            terms.extend(
                {**row, "borrower_id": borrower_id}
                for row in sources[INPUT_FILES[1]]
                if row["borrower_id"] == template_id
            )
    _write_csv(output_directory / "borrowers.csv", borrowers, list(borrowers[0]))
    _write_csv(
        output_directory / "quarterly_financials.csv",
        financials,
        ("borrower_id", "period_end", *FINANCIAL_METRICS),
    )
    terms_path = output_directory / "covenant_terms.csv"
    _write_csv(terms_path, terms, list(terms[0]))
    covenant_reader = SyntheticCovenantReader(terms_path)
    indexed_financials = {(row["borrower_id"], row["period_end"]): row for row in financials}
    feature_records, training_rows, outcome_records, calculation_records = [], [], [], []
    with TemporaryDirectory(prefix="synthetic-analytics-") as temporary_directory:
        repository = CovenantResultRepository(Path(temporary_directory) / "analytics.sqlite3")
        feature_builder = RiskFeatureBuilder(repository)
        for borrower in borrowers:
            borrower_id = borrower["borrower_id"]
            run_id = f"simulation:{GENERATOR_VERSION}:{seed}:{borrower_id}"
            results_by_period = {}
            for period in QUARTERS:
                raw = indexed_financials[(borrower_id, period.isoformat())]
                financial_period = FinancialPeriod(
                    borrower_id=borrower_id,
                    period_end=period,
                    metrics={name: raw.get(name) for name in FINANCIAL_METRICS},
                    source_file="quarterly_financials.csv",
                )
                resolutions = covenant_reader.resolve(borrower_id, period, period, financial_period)
                for resolution in resolutions:
                    evidence_records = list(resolution.evidence)
                    if resolution.covenant is not None:
                        evidence_records.extend(resolution.covenant.evidence)
                    for evidence in evidence_records:
                        evidence["source_file"] = "covenant_terms.csv"
                results = [
                    calculate_covenant(
                        resolution,
                        financial_period,
                        assessment_run_id=run_id,
                        information_cutoff=period,
                    )
                    for resolution in resolutions
                ]
                for result in results:
                    result.result_id = f"{run_id}:{period}:{result.covenant_id}"
                    result.created_at = datetime.combine(period, datetime.min.time(), tzinfo=UTC)
                    calculation_records.append(result.model_dump(mode="json"))
                results_by_period[period] = results
                repository.save_all(results)
            for quarter_index, period in enumerate(QUARTERS):
                features = feature_builder.build(
                    borrower_id, period, period, assessment_run_id=run_id
                )
                sample_id = f"{borrower_id}:{period}"
                next_period = QUARTERS[quarter_index + 1] if quarter_index < 7 else None
                label, reason = outcome_label(results_by_period.get(next_period, []))
                split = evaluation_split(borrower["partition_role"], period, label)
                if not has_usable_current_inputs(features):
                    split = "unused"
                feature_records.append(
                    {"sample_id": sample_id, "features": features.model_dump(mode="json")}
                )
                training_rows.append(
                    {
                        "sample_id": sample_id,
                        "borrower_id": borrower_id,
                        "period_end": period.isoformat(),
                        "split": split,
                        "target": label,
                        **model_feature_row(features),
                    }
                )
                outcome_records.append(
                    {
                        "sample_id": sample_id,
                        "target": label,
                        "reason": reason,
                        "current_inputs_usable": has_usable_current_inputs(features),
                        "outcome_period_end": next_period.isoformat() if next_period else None,
                        "source_result_ids": [
                            result.result_id for result in results_by_period.get(next_period, [])
                        ],
                    }
                )
    _write_csv(
        output_directory / "training.csv",
        training_rows,
        ("sample_id", "borrower_id", "period_end", "split", "target", *FEATURE_COLUMNS),
    )
    _write_jsonl(output_directory / "features.jsonl", feature_records)
    _write_jsonl(output_directory / "outcomes.jsonl", outcome_records)
    _write_jsonl(output_directory / "calculations.jsonl", calculation_records)
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "borrowers_per_scenario": borrowers_per_scenario,
        "borrower_count": len(borrowers),
        "observation_count": len(training_rows),
        "feature_schema_version": "v1",
        "model_feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "prediction_target": "any_covenant_breach",
        "horizon_quarters": 1,
        "training_data_origin": "synthetic",
        "information_assumption": "Simulated quarter-end inputs; publication dates unknown.",
        "simulation_defaults": DEFAULT_METRICS,
        "scenario_drift": SCENARIO_DRIFT,
        "scenario_counts": dict(Counter(row["scenario"] for row in borrowers)),
        "split_counts": dict(Counter(row["split"] for row in training_rows)),
        "partition_labels": {
            partition: dict(
                Counter(str(row["target"]) for row in training_rows if row["split"] == partition)
            )
            for partition in ("train", "validation", "test")
        },
        "label_counts": dict(Counter(str(row["target"]) for row in training_rows)),
        "exclusion_counts": dict(
            Counter(row["reason"] for row in outcome_records if row["target"] is None)
        ),
        "missing_counts": {
            column: sum(row[column] is None for row in training_rows) for column in FEATURE_COLUMNS
        },
        "source_hashes": {name: file_hash(source_directory / name) for name in INPUT_FILES},
        "output_hashes": {
            path.name: file_hash(path)
            for path in sorted(output_directory.iterdir())
            if path.name
            in (
                "borrowers.csv",
                "quarterly_financials.csv",
                "covenant_terms.csv",
                "training.csv",
                "features.jsonl",
                "outcomes.jsonl",
                "calculations.jsonl",
            )
        },
    }
    write_json(output_directory / "manifest.json", manifest)
    return manifest
