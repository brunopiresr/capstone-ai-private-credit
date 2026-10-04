"""Exercise ingestion and queries against real temporary SQLite files."""

import csv
import sqlite3
from pathlib import Path

import pytest

from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials

SOURCE = Path(__file__).resolve().parents[3] / "data" / "synthetic_quarterly_financials.csv"


def write_csv(path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header or ["borrower_id", "period_end", "total_debt", "cash"])
        writer.writerows(rows)
    return path


def test_load_real_dataset_and_query_facts(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "financials.sqlite3"
    result = load_financials(SOURCE, database)
    assert result.rows_loaded == 22
    assert result.borrowers_loaded == 12
    assert result.database_path == database
    repository = FinancialRepository(database)
    quarter = repository.get_quarter("SYN007", "2025-09-30")
    assert quarter["total_debt"] is None
    assert quarter["financials_debt"] == 100
    assert quarter["compliance_certificate_debt"] == 110
    assert quarter["source_file"] == str(SOURCE)
    assert quarter["source_row"] == 14
    assert "conflict" in quarter["notes"]
    missing = repository.get_facts("SYN007", "2025-09-30", metric_name="total_debt")
    assert missing[0]["value"] is None
    assert missing[0]["data_quality_status"] == "missing"
    assert missing[0]["unit"] is None
    zero = repository.get_facts("SYN011", "2025-09-30", metric_name="eligible_addbacks")
    assert zero[0]["value"] == 0
    assert zero[0]["data_quality_status"] == "provided"
    percentage = repository.get_facts(
        "SYN010", "2025-06-30", metric_name="revolver_availability_pct"
    )
    assert percentage[0]["value"] == 40
    assert percentage[0]["unit"] == "percent"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM quarterly_financials").fetchone()[0] == 22
        assert connection.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0] == 308


def test_reload_updates_snapshot_and_preserves_other_quarters(tmp_path: Path) -> None:
    database = tmp_path / "financials.sqlite3"
    load_financials(SOURCE, database)
    load_financials(SOURCE, database)
    source = write_csv(tmp_path / "updated.csv", [["SYN001", "2025-03-31", "121.25", ""]])
    load_financials(source, database)
    repository = FinancialRepository(database)
    updated = repository.get_quarter("SYN001", "2025-03-31")
    assert updated["total_debt"] == 121.25
    assert updated["cash"] is None
    assert updated["reported_ebitda"] is None
    assert updated["source_file"] == str(source)
    assert len(repository.get_history("SYN001")) == 3
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM quarterly_financials").fetchone()[0] == 22


@pytest.mark.parametrize(
    ("bad_row", "message"),
    [
        (["SYN001", "2025-03-31", "oops", ""], "total_debt"),
        (["SYN001", "2025-03-31", "NaN", ""], "finite number"),
        (["SYN001", "2025-03-31", "inf", ""], "finite number"),
        (["SYN001", "2025-03-31", "1e999", ""], "finite number"),
        (["SYN001", "2025-02-30", "120", ""], "YYYY-MM-DD"),
        (["SYN001", "20250331", "120", ""], "YYYY-MM-DD"),
        (["", "2025-03-31", "120", ""], "borrower_id is empty"),
        (["SYN001", "2025-03-31", "120"], "wrong number of fields"),
        (["SYN001", "2025-03-31", "120", "", "extra"], "wrong number of fields"),
    ],
)
def test_invalid_csv_leaves_database_unchanged(
    tmp_path: Path, bad_row: list[str], message: str
) -> None:
    database = tmp_path / "financials.sqlite3"
    load_financials(SOURCE, database)
    source = write_csv(tmp_path / "invalid.csv", [["SYN001", "2025-06-30", "999", "0"], bad_row])
    with pytest.raises(ValueError, match=message):
        load_financials(source, database)
    assert FinancialRepository(database).get_quarter("SYN001", "2025-06-30")["total_debt"] == 118


@pytest.mark.parametrize(
    ("header", "rows", "message"),
    [
        (["borrower_id", "total_debt"], [], "Missing required"),
        (["borrower_id", "period_end", "typo"], [], "Unknown financial"),
        (["borrower_id", "period_end", "cash", "cash"], [], "duplicate column"),
        (["borrower_id", "period_end"], [], "at least one financial"),
        (["borrower_id", "period_end", "cash"], [], "no data records"),
        (
            ["borrower_id", "period_end", "cash"],
            [["A", "2025-03-31", "0"], ["A", "2025-03-31", "1"]],
            "duplicate borrower/period",
        ),
        (
            ["borrower_id", "period_end", "revolver_availability_pct"],
            [["A", "2025-03-31", "101"]],
            "between 0 and 100",
        ),
    ],
)
def test_invalid_structure_does_not_create_database(
    tmp_path: Path, header: list[str], rows: list[list[str]], message: str
) -> None:
    database = tmp_path / "financials.sqlite3"
    source = write_csv(tmp_path / "invalid.csv", rows, header)
    with pytest.raises(ValueError, match=message):
        load_financials(source, database)
    assert not database.exists()


def test_query_history_and_parameterized_identifiers(tmp_path: Path) -> None:
    database = tmp_path / "financials.sqlite3"
    load_financials(SOURCE, database)
    repository = FinancialRepository(database)
    history = repository.get_history("SYN002", as_of="2025-09-30")
    assert [row["period_end"] for row in history] == ["2025-03-31", "2025-06-30", "2025-09-30"]
    assert repository.get_quarter("unknown", "2025-03-31") is None
    assert repository.get_history("' OR 1=1 --") == []
    assert repository.get_facts("unknown", "2025-03-31") == []
    with pytest.raises(ValueError, match="Unknown financial metric"):
        repository.get_facts("SYN001", "2025-03-31", metric_name="typo")
    with pytest.raises(FileNotFoundError, match="Load the financial CSV first"):
        FinancialRepository(tmp_path / "absent.sqlite3")


def test_database_write_failure_rolls_back_entire_import(tmp_path: Path) -> None:
    database = tmp_path / "financials.sqlite3"
    load_financials(SOURCE, database)
    with sqlite3.connect(database) as connection:
        connection.execute("""
            CREATE TRIGGER reject_quarter_update BEFORE UPDATE ON quarterly_financials
            WHEN NEW.borrower_id = 'SYN002'
            BEGIN SELECT RAISE(ABORT, 'rejected update'); END
        """)
    source = write_csv(
        tmp_path / "updated.csv",
        [["SYN001", "2025-03-31", "999", "0"], ["SYN002", "2025-03-31", "999", "0"]],
    )
    with pytest.raises(sqlite3.IntegrityError, match="rejected update"):
        load_financials(source, database)
    repository = FinancialRepository(database)
    assert repository.get_quarter("SYN001", "2025-03-31")["total_debt"] == 120
    assert repository.get_quarter("SYN002", "2025-03-31")["total_debt"] == 135
