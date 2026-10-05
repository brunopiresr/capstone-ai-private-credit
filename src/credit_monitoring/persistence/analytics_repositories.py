"""Append-only calculation, feature, and prediction repositories."""

import json
from datetime import date
from pathlib import Path

from credit_monitoring.domain.assessment import CovenantResult
from credit_monitoring.domain.risk_features import BorrowerFeatureSnapshot
from credit_monitoring.domain.risk_prediction import RiskPrediction

from .database import open_database


def initialize_analytics(database_path: str | Path) -> None:
    """Create analytics tables without changing source financial or extraction databases."""
    schema = Path(__file__).with_name("analytics_schema.sql").read_text(encoding="utf-8")
    with open_database(database_path) as connection:
        connection.executescript(schema)


def _insert(connection, table: str, values: dict) -> None:
    """Insert an application-owned record; table and column names are internal constants."""
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


def _result_from_row(row) -> CovenantResult:
    values = dict(row)
    for field in ("resolved_covenant", "financial_inputs", "evidence", "issues"):
        serialized = values.pop(f"{field}_json")
        values[field] = None if serialized is None else json.loads(serialized)
    return CovenantResult.model_validate(values)


class CovenantResultRepository:
    """Store reproducible results and read bounded borrower history."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        initialize_analytics(self.database_path)

    def save_all(self, results: list[CovenantResult]) -> None:
        """Insert a calculation run atomically, rejecting duplicate identifiers."""
        with open_database(self.database_path) as connection:
            for result in results:
                values = result.model_dump(mode="json")
                for field in ("resolved_covenant", "financial_inputs", "evidence", "issues"):
                    value = values.pop(field)
                    values[f"{field}_json"] = None if value is None else json.dumps(value)
                _insert(connection, "covenant_results", values)

    def get_history(
        self,
        borrower_id: str,
        *,
        period_end: date,
        information_cutoff: date,
        assessment_run_id: str | None = None,
    ) -> list[CovenantResult]:
        """Return one latest result per covenant-period, optionally within a specific run."""
        query = (
            "SELECT * FROM covenant_results WHERE borrower_id = ? AND period_end <= ? "
            "AND information_cutoff <= ?"
        )
        parameters = [borrower_id, period_end.isoformat(), information_cutoff.isoformat()]
        if assessment_run_id is not None:
            query += " AND assessment_run_id = ?"
            parameters.append(assessment_run_id)
        query += " ORDER BY created_at DESC, rowid DESC"
        with open_database(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        latest = {}
        for row in rows:
            key = (row["covenant_id"], row["period_end"])
            if key not in latest:
                latest[key] = _result_from_row(row)
        return sorted(latest.values(), key=lambda result: (result.period_end, result.covenant_id))


class RiskFeatureSnapshotRepository:
    """Persist exact feature vectors after validating their calculation references."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        initialize_analytics(self.database_path)

    def save(self, snapshot: BorrowerFeatureSnapshot) -> None:
        """Validate referenced results and append a snapshot in the same transaction."""
        features = snapshot.features
        with open_database(self.database_path) as connection:
            current_covenants = set()
            for result_id in snapshot.source_result_ids:
                row = connection.execute(
                    "SELECT * FROM covenant_results WHERE result_id = ?",
                    (result_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown source calculation: {result_id}")
                if (
                    row["borrower_id"] != features.borrower_id
                    or row["assessment_run_id"] != snapshot.assessment_run_id
                    or row["period_end"] > features.period_end.isoformat()
                    or row["information_cutoff"] > features.information_cutoff.isoformat()
                ):
                    raise ValueError("Feature references must belong to the bounded borrower run.")
                if row["period_end"] == features.period_end.isoformat():
                    current_covenants.add(row["covenant_id"])
            if current_covenants != {item.covenant_id for item in features.covenants}:
                raise ValueError("Features must reference all their current covenant results.")
            _insert(
                connection,
                "risk_feature_snapshots",
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "assessment_run_id": snapshot.assessment_run_id,
                    "borrower_id": features.borrower_id,
                    "period_end": features.period_end.isoformat(),
                    "information_cutoff": features.information_cutoff.isoformat(),
                    "feature_schema_version": features.feature_schema_version,
                    "features_json": features.model_dump_json(),
                    "source_result_ids_json": json.dumps(snapshot.source_result_ids),
                    "created_at": snapshot.created_at.isoformat(),
                },
            )

    def get(self, snapshot_id: str) -> BorrowerFeatureSnapshot | None:
        """Read a stored vector without consulting mutable source financial rows."""
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM risk_feature_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return BorrowerFeatureSnapshot(
            snapshot_id=row["snapshot_id"],
            assessment_run_id=row["assessment_run_id"],
            features=json.loads(row["features_json"]),
            source_result_ids=json.loads(row["source_result_ids_json"]),
            created_at=row["created_at"],
        )


class RiskPredictionRepository:
    """Store model outputs with a checked feature-snapshot identity."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        initialize_analytics(self.database_path)

    def save(self, prediction: RiskPrediction) -> None:
        """Reject mismatched borrower-period output before inserting a prediction."""
        with open_database(self.database_path) as connection:
            snapshot = connection.execute(
                "SELECT borrower_id, period_end FROM risk_feature_snapshots WHERE snapshot_id = ?",
                (prediction.snapshot_id,),
            ).fetchone()
            if snapshot is None or (
                snapshot["borrower_id"] != prediction.borrower_id
                or snapshot["period_end"] != prediction.period_end.isoformat()
            ):
                raise ValueError("Prediction must identify its stored borrower-period snapshot.")
            values = prediction.model_dump(mode="json", exclude={"borrower_id", "period_end"})
            values["top_drivers_json"] = json.dumps(values.pop("top_drivers"))
            _insert(connection, "risk_predictions", values)

    def get(self, prediction_id: str) -> RiskPrediction | None:
        """Join snapshot identity when reconstructing a stored prediction."""
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT p.*, s.borrower_id, s.period_end FROM risk_predictions p "
                "JOIN risk_feature_snapshots s ON s.snapshot_id = p.snapshot_id "
                "WHERE p.prediction_id = ?",
                (prediction_id,),
            ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["top_drivers"] = json.loads(values.pop("top_drivers_json"))
        return RiskPrediction.model_validate(values)
