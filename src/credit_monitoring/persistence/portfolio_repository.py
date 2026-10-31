"""Persist complete portfolio assessments and reviews without altering source inputs."""

from datetime import date
from pathlib import Path

from credit_monitoring.domain.analytics_base import utc_now
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult
from credit_monitoring.persistence.database import open_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_assessments (
    run_id TEXT PRIMARY KEY,
    borrower_id TEXT NOT NULL,
    period_end TEXT NOT NULL,
    information_cutoff TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json))
);
CREATE INDEX IF NOT EXISTS idx_portfolio_assessment_lookup
    ON portfolio_assessments(borrower_id, period_end, information_cutoff);
CREATE TABLE IF NOT EXISTS portfolio_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES portfolio_assessments(run_id),
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json))
);
CREATE INDEX IF NOT EXISTS idx_portfolio_review_run ON portfolio_reviews(run_id);
CREATE TABLE IF NOT EXISTS portfolio_assessment_attempts (
    borrower_id TEXT NOT NULL,
    period_end TEXT NOT NULL,
    information_cutoff TEXT NOT NULL,
    created_at TEXT NOT NULL,
    error TEXT
);
"""


class PortfolioRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        with open_database(self.database_path) as connection:
            connection.executescript(SCHEMA)

    def save_assessment(self, assessment: RiskAssessment) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO portfolio_assessments VALUES (?, ?, ?, ?, ?, ?)",
                (
                    assessment.assessment_run_id,
                    assessment.borrower_id,
                    assessment.period_end.isoformat(),
                    assessment.information_cutoff.isoformat(),
                    utc_now().isoformat(),
                    assessment.model_dump_json(),
                ),
            )
            self._attempt(
                connection,
                assessment.borrower_id,
                assessment.period_end,
                assessment.information_cutoff,
                None,
            )

    @staticmethod
    def _attempt(
        connection, borrower_id: str, period_end: date, cutoff: date, error: str | None
    ) -> None:
        connection.execute(
            "INSERT INTO portfolio_assessment_attempts VALUES (?, ?, ?, ?, ?)",
            (borrower_id, period_end.isoformat(), cutoff.isoformat(), utc_now().isoformat(), error),
        )

    def save_failure(self, borrower_id: str, period_end: date, cutoff: date, error: str) -> None:
        with open_database(self.database_path) as connection:
            self._attempt(connection, borrower_id, period_end, cutoff, error)

    def latest_assessment(
        self, borrower_id: str, period_end: date, cutoff: date
    ) -> tuple[RiskAssessment, str] | None:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT result_json, created_at FROM portfolio_assessments "
                "WHERE borrower_id = ? AND period_end = ? AND information_cutoff <= ? "
                "ORDER BY information_cutoff DESC, rowid DESC LIMIT 1",
                (borrower_id, period_end.isoformat(), cutoff.isoformat()),
            ).fetchone()
        return (
            (RiskAssessment.model_validate_json(row["result_json"]), row["created_at"])
            if row
            else None
        )

    def latest_error(self, borrower_id: str, period_end: date, cutoff: date) -> str | None:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT error FROM portfolio_assessment_attempts WHERE borrower_id = ? "
                "AND period_end = ? AND information_cutoff <= ? "
                "ORDER BY information_cutoff DESC, rowid DESC LIMIT 1",
                (borrower_id, period_end.isoformat(), cutoff.isoformat()),
            ).fetchone()
        return row["error"] if row else None

    def get_assessment(self, run_id: str) -> RiskAssessment:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT result_json FROM portfolio_assessments WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Choose a saved assessment before running a credit review.")
        return RiskAssessment.model_validate_json(row["result_json"])

    def assessment_created_at(self, run_id: str) -> str:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT created_at FROM portfolio_assessments WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Choose a saved assessment.")
        return row["created_at"]

    def all_assessments(self) -> list[RiskAssessment]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT result_json FROM portfolio_assessments ORDER BY rowid"
            ).fetchall()
        return [RiskAssessment.model_validate_json(row["result_json"]) for row in rows]

    def save_review(self, review: CreditReviewResult) -> None:
        assessment = self.get_assessment(review.snapshot.assessment_run_id)
        if (
            review.snapshot.borrower_id,
            review.snapshot.period_end,
            review.snapshot.information_cutoff,
        ) != (
            assessment.borrower_id,
            assessment.period_end,
            assessment.information_cutoff,
        ):
            raise ValueError("Review identity must match its saved assessment.")
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO portfolio_reviews VALUES (?, ?, ?, ?)",
                (
                    review.review_id,
                    assessment.assessment_run_id,
                    review.created_at.isoformat(),
                    review.model_dump_json(),
                ),
            )

    def latest_review(self, run_id: str) -> CreditReviewResult | None:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT result_json FROM portfolio_reviews WHERE run_id = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return CreditReviewResult.model_validate_json(row["result_json"]) if row else None

    def get_review(self, review_id: str) -> CreditReviewResult:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT result_json FROM portfolio_reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Choose a saved credit review.")
        return CreditReviewResult.model_validate_json(row["result_json"])

    def assessment_history(self, borrower_id: str) -> list[tuple[RiskAssessment, str]]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT result_json, created_at FROM portfolio_assessments "
                "WHERE borrower_id = ? ORDER BY rowid DESC",
                (borrower_id,),
            ).fetchall()
        return [
            (RiskAssessment.model_validate_json(r["result_json"]), r["created_at"]) for r in rows
        ]

    def review_history(self, run_id: str) -> list[CreditReviewResult]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT result_json FROM portfolio_reviews WHERE run_id = ? ORDER BY rowid DESC",
                (run_id,),
            ).fetchall()
        return [CreditReviewResult.model_validate_json(row["result_json"]) for row in rows]
