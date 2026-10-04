"""Parameterized queries for the SQLite financial repository."""

from pathlib import Path

from credit_monitoring.financials.mappings import FINANCIAL_METRICS
from credit_monitoring.persistence.database import open_database


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
