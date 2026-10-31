"""Back up, build, validate and atomically replace only the requested working database."""

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from credit_monitoring.application.document_workspace import DocumentWorkspace
from credit_monitoring.covenants.repositories import CovenantRepository
from credit_monitoring.domain import ExtractionResult
from credit_monitoring.domain.analytics_base import new_identifier
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.persistence.analytics_repositories import (
    CovenantResultRepository,
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
    initialize_analytics,
)
from credit_monitoring.persistence.database import open_database


def check_database(path: Path) -> None:
    with open_database(path) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Replacement database failed its integrity check.")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Replacement database has broken references.")


def recreate_database(workspace: DocumentWorkspace, target: str, *, progress=None) -> dict:
    destinations = {
        "Financial database": workspace.working_dir / "financials.sqlite3",
        "Extraction database": workspace.processor.repository.database_path,
        "Analytics database": workspace.working_dir / "analytics.sqlite3",
    }
    if target not in destinations:
        raise ValueError("Choose a supported working database.")
    path = destinations[target]
    with workspace.operation(f"Recreate {target.lower()}", [str(path)]) as outcomes:

        def stage(message):
            if progress:
                progress(message)

        stage("Checking source inputs")
        if target == "Financial database":
            source = (
                workspace.data_root / "app" / "synthetic" / "synthetic_quarterly_financials.csv"
            )
            if not source.is_file():
                raise ValueError(f"Financial source CSV is missing: {source}")
        elif target == "Extraction database" and not workspace.archive_path.is_file():
            raise ValueError(
                "Extraction archive is missing. Process a document to retain its records."
            )
        elif (
            target == "Analytics database" and not workspace.portfolio.repository.all_assessments()
        ):
            raise ValueError("No retained assessments are available to restore analytics.")
        backup = workspace.working_dir / "backups" / f"{path.stem}-{new_identifier()}.sqlite3"
        backup.parent.mkdir(parents=True, exist_ok=True)
        stage("Backing up the working database")
        if path.is_file():
            with sqlite3.connect(path) as original, sqlite3.connect(backup) as retained:
                original.backup(retained)
        else:
            backup = None
        with TemporaryDirectory(dir=workspace.working_dir) as temporary:
            replacement = Path(temporary) / path.name
            stage("Building replacement")
            if target == "Financial database":
                loaded = load_financials(source, replacement)
                count = loaded.rows_loaded
            elif target == "Extraction database":
                count = restore_extractions(workspace.archive_path, replacement)
            else:
                count = restore_analytics(workspace, replacement)
            stage("Validating replacement")
            check_database(replacement)
            stage("Publishing validated replacement")
            replacement.replace(path)
        if target == "Financial database":
            workspace.portfolio.financial_repository = FinancialRepository(path)
            workspace.portfolio.assessment_service.financial_repository = (
                workspace.portfolio.financial_repository
            )
            for borrower in workspace.borrowers:
                workspace.workflow.source_changed(borrower, None, "Financial database recreated.")
        elif target == "Extraction database":
            workspace.processor.repository = CovenantRepository(path)
        workspace.processor.evidence_search.clear()
        summary = {
            "status": "complete",
            "target": str(path),
            "records": count,
            "backup": str(backup) if backup else None,
        }
        outcomes.append(summary)
    return summary


def restore_extractions(archive_path: Path, replacement: Path) -> int:
    archive = json.loads(archive_path.read_text())
    if archive.get("version") != 1:
        raise ValueError("Unsupported extraction archive version.")
    CovenantRepository(replacement)
    with open_database(replacement) as connection:
        for table in ("document_extractions", "document_extraction_sections"):
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            for row in archive[table]:
                if row.get("result_json"):
                    ExtractionResult.model_validate_json(row["result_json"])
                if table == "document_extractions":
                    json.loads(row["metadata_json"])
                    json.loads(row["configuration_json"])
                    if row["status"] not in {"complete", "failed", "processing"}:
                        raise ValueError("Invalid cached extraction status.")
                    if row["status"] == "complete" and not row.get("result_json"):
                        raise ValueError("A complete cached extraction requires its facts.")
                connection.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                    f"({', '.join('?' for _ in columns)})",
                    [row[c] for c in columns],
                )
        for record in connection.execute("SELECT * FROM document_extractions"):
            indices = [
                r[0]
                for r in connection.execute(
                    "SELECT section_index FROM document_extraction_sections "
                    "WHERE document_id = ? AND cache_key = ?",
                    (record["document_id"], record["cache_key"]),
                )
            ]
            if any(index < 0 or index >= record["total_sections"] for index in indices):
                raise ValueError("Cached section indices are outside the document range.")
            if record["status"] == "complete" and sorted(indices) != list(
                range(record["total_sections"])
            ):
                raise ValueError("A complete extraction archive must retain every section.")
    return len(archive["document_extractions"])


def restore_analytics(workspace: DocumentWorkspace, replacement: Path) -> int:
    initialize_analytics(replacement)
    results = CovenantResultRepository(replacement)
    features = RiskFeatureSnapshotRepository(replacement)
    predictions = RiskPredictionRepository(replacement)
    count = 0
    for assessment in workspace.portfolio.repository.all_assessments():
        if not assessment.verification.is_valid:
            continue
        results.save_all(assessment.history + assessment.results)
        count += len(assessment.history + assessment.results)
        if assessment.feature_snapshot:
            features.save(assessment.feature_snapshot)
            if assessment.prediction:
                predictions.save(assessment.prediction)
    return count
