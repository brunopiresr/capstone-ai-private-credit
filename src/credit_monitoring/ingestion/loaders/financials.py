"""Validate and atomically load quarterly financial CSV data into SQLite."""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from credit_monitoring.financials.mappings import FINANCIAL_METRICS
from credit_monitoring.persistence.database import open_database
from credit_monitoring.persistence.schema import initialize_financial_schema


@dataclass(frozen=True)
class FinancialLoadResult:
    """Summary of records inserted or updated by one successful import."""

    database_path: Path
    rows_loaded: int
    borrowers_loaded: int


def _read_financials(csv_path: Path) -> list[dict[str, str | float | int | None]]:
    records = []
    seen = set()
    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames
        if not headers:
            raise ValueError("Financial CSV is empty or has no header")
        if len(headers) != len(set(headers)):
            raise ValueError("Financial CSV contains duplicate column names")
        required = {"borrower_id", "period_end"}
        allowed = required | set(FINANCIAL_METRICS) | {"notes"}
        if missing := required - set(headers):
            raise ValueError(f"Missing required CSV columns: {sorted(missing)}")
        if unknown := set(headers) - allowed:
            raise ValueError(f"Unknown financial CSV columns: {sorted(unknown)}")
        if not set(headers) & set(FINANCIAL_METRICS):
            raise ValueError("Financial CSV must contain at least one financial metric column")

        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV line {line}: wrong number of fields")
            borrower_id = row["borrower_id"].strip()
            period_end = row["period_end"].strip()
            if not borrower_id:
                raise ValueError(f"CSV line {line}: borrower_id is empty")
            try:
                parsed_date = date.fromisoformat(period_end)
                if parsed_date.isoformat() != period_end:
                    raise ValueError("noncanonical date")
            except ValueError as error:
                raise ValueError(
                    f"CSV line {line}: period_end must be a YYYY-MM-DD date"
                ) from error
            key = (borrower_id, period_end)
            if key in seen:
                raise ValueError(f"CSV line {line}: duplicate borrower/period {key}")
            seen.add(key)
            record: dict[str, str | float | int | None] = {
                "borrower_id": borrower_id,
                "period_end": period_end,
                "notes": row.get("notes", "").strip() or None,
                "source_file": str(csv_path),
                "source_row": line,
            }
            for metric in FINANCIAL_METRICS:
                value = row.get(metric, "").strip()
                if not value:
                    record[metric] = None
                    continue
                try:
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError("nonfinite number")
                except ValueError as error:
                    raise ValueError(
                        f"CSV line {line}: {metric} must be a finite number or blank"
                    ) from error
                if metric == "revolver_availability_pct" and not 0 <= number <= 100:
                    raise ValueError(f"CSV line {line}: {metric} must be between 0 and 100")
                record[metric] = number
            records.append(record)
    if not records:
        raise ValueError("Financial CSV contains no data records")
    return records


def load_financials(csv_path: str | Path, database_path: str | Path) -> FinancialLoadResult:
    """Load a CSV as the current snapshot for each borrower/period.

    Blank cells and omitted metric columns become SQL NULL. A repeated load
    replaces matching snapshots, including values changed to blank. Other
    borrower/period records are retained. Validation completes before any writes,
    and all upserts commit together. Monetary values use SQLite REAL; their
    currency and scale are not inferred. Notes are preserved source metadata,
    and may contain benchmark outcome labels unsuitable for model prompts.
    """
    source = Path(csv_path).expanduser().resolve()
    target = Path(database_path).expanduser().resolve()
    if source == target:
        raise ValueError("CSV source and database destination must be different files")
    records = _read_financials(source)
    columns = (
        "borrower_id",
        "period_end",
        *FINANCIAL_METRICS,
        "notes",
        "source_file",
        "source_row",
    )
    updates = ", ".join(
        f"{column} = excluded.{column}" for column in columns if column not in columns[:2]
    )
    placeholders = ", ".join(f":{column}" for column in columns)
    statement = f"""
        INSERT INTO quarterly_financials ({", ".join(columns)}) VALUES ({placeholders})
        ON CONFLICT (borrower_id, period_end) DO UPDATE SET
            {updates}, loaded_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    """
    with open_database(target) as connection:
        initialize_financial_schema(connection)
        connection.executemany(statement, records)
    return FinancialLoadResult(
        database_path=target,
        rows_loaded=len(records),
        borrowers_loaded=len({record["borrower_id"] for record in records}),
    )


def main() -> None:
    """Provide a module entry point without requiring notebook changes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Quarterly financial CSV")
    parser.add_argument("--db", required=True, type=Path, help="Destination SQLite file")
    args = parser.parse_args()
    try:
        result = load_financials(args.csv, args.db)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Financial import failed: {error}\n")
    print(
        f"Loaded {result.rows_loaded} quarterly records for {result.borrowers_loaded} borrowers "
        f"into {result.database_path}"
    )


if __name__ == "__main__":
    main()
