"""Parameterized queries for the SQLite financial repository."""

from datetime import date
from pathlib import Path

from credit_monitoring.domain.assessment import FinancialPeriod
from credit_monitoring.financials.mappings import FINANCIAL_METRICS
from credit_monitoring.persistence.database import open_database


def financial_period_from_row(row: dict) -> FinancialPeriod:
    """Copy source metadata; loaded_at is not publication availability."""
    return FinancialPeriod(
        borrower_id=row["borrower_id"],
        period_end=row["period_end"],
        metrics={metric: row.get(metric) for metric in FINANCIAL_METRICS},
        source_file=row.get("source_file"),
        source_row=row.get("source_row"),
        loaded_at=row.get("loaded_at"),
        available_at=row.get("available_at"),
        currency=row.get("currency"),
        scale=row.get("scale"),
        debt_source_status=row.get("debt_source_status"),
    )


class FinancialRepository:
    """Read source snapshots and normalized facts from a loaded SQLite file."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(f"Load the financial CSV first: {self.database_path}")

    def get_quarter(self, borrower_id: str, period_end: str) -> dict | None:
        """Return one snapshot, including provenance, or None if absent.

        Notes may include benchmark outcome labels; do not use them as agent inputs.
        """
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM quarterly_financials WHERE borrower_id = ? AND period_end = ?",
                (borrower_id, period_end),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_history(self, borrower_id: str, *, as_of: str | None = None) -> list[dict]:
        """Return snapshots ordered by period, optionally capped at a reporting date.

        The cutoff filters reporting periods, not when data became available.
        """
        query = "SELECT * FROM quarterly_financials WHERE borrower_id = ?"
        parameters = [borrower_id]
        if as_of is not None:
            query += " AND period_end <= ?"
            parameters.append(as_of)
        query += " ORDER BY period_end"
        with open_database(self.database_path) as connection:
            return [dict(row) for row in connection.execute(query, parameters)]

    def get_period(self, borrower_id: str, period_end: date) -> FinancialPeriod | None:
        """Return sanitized typed inputs, retaining unknown availability as unknown."""
        row = self.get_quarter(borrower_id, period_end.isoformat())
        return financial_period_from_row(row) if row is not None else None

    def get_period_history(
        self, borrower_id: str, *, as_of: date | None = None
    ) -> list[FinancialPeriod]:
        """Read typed history bounded by reporting date, without benchmark notes."""
        return [
            financial_period_from_row(row)
            for row in self.get_history(borrower_id, as_of=as_of.isoformat() if as_of else None)
        ]

    def get_facts(
        self, borrower_id: str, period_end: str, *, metric_name: str | None = None
    ) -> list[dict]:
        """Return normalized input facts, including explicitly missing values."""
        if metric_name is not None and metric_name not in FINANCIAL_METRICS:
            raise ValueError(f"Unknown financial metric: {metric_name}")
        query = "SELECT * FROM financial_facts WHERE borrower_id = ? AND period_end = ?"
        parameters = [borrower_id, period_end]
        if metric_name is not None:
            query += " AND metric_name = ?"
            parameters.append(metric_name)
        query += " ORDER BY metric_name"
        with open_database(self.database_path) as connection:
            return [dict(row) for row in connection.execute(query, parameters)]
