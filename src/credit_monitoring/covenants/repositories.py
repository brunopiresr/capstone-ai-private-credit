"""SQLite document and section extraction cache; no model calls inside transactions."""

import json
from pathlib import Path

from credit_monitoring.domain import ExtractionResult
from credit_monitoring.persistence.database import open_database


class CovenantRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        with open_database(self.database_path) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS document_extractions (
                    document_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_sections INTEGER NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (document_id, cache_key)
                );
                CREATE TABLE IF NOT EXISTS document_extraction_sections (
                    document_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    section_index INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY (document_id, cache_key, section_index),
                    FOREIGN KEY (document_id, cache_key)
                        REFERENCES document_extractions(document_id, cache_key) ON DELETE CASCADE
                );
            """)

    def get(self, document_id: str, cache_key: str) -> dict | None:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM document_extractions WHERE document_id = ? AND cache_key = ?",
                (document_id, cache_key),
            ).fetchone()
        return dict(row) if row else None

    def has_document(self, document_id: str) -> bool:
        with open_database(self.database_path) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM document_extractions WHERE document_id = ? LIMIT 1",
                    (document_id,),
                ).fetchone()
                is not None
            )

    def begin(
        self,
        document_id: str,
        cache_key: str,
        *,
        metadata: dict,
        configuration: dict,
        total_sections: int,
        force: bool,
    ) -> None:
        with open_database(self.database_path) as connection:
            if force:
                connection.execute(
                    "DELETE FROM document_extractions WHERE document_id = ? AND cache_key = ?",
                    (document_id, cache_key),
                )
            connection.execute(
                """
                INSERT INTO document_extractions
                    (document_id, cache_key, metadata_json, configuration_json,
                     status, total_sections)
                VALUES (?, ?, ?, ?, 'processing', ?)
                ON CONFLICT(document_id, cache_key) DO UPDATE SET
                    status = 'processing', result_json = NULL, error = NULL,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (
                    document_id,
                    cache_key,
                    json.dumps(metadata),
                    json.dumps(configuration),
                    total_sections,
                ),
            )

    def sections(self, document_id: str, cache_key: str) -> dict[int, ExtractionResult]:
        with open_database(self.database_path) as connection:
            return {
                row["section_index"]: ExtractionResult.model_validate_json(row["result_json"])
                for row in connection.execute(
                    "SELECT section_index, result_json FROM document_extraction_sections "
                    "WHERE document_id = ? AND cache_key = ? ORDER BY section_index",
                    (document_id, cache_key),
                )
            }

    def section_count(self, document_id: str, cache_key: str) -> int:
        """State inspection should not deserialize every successful section's facts."""
        with open_database(self.database_path) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM document_extraction_sections "
                "WHERE document_id = ? AND cache_key = ?",
                (document_id, cache_key),
            ).fetchone()[0]

    def save_section(
        self, document_id: str, cache_key: str, index: int, result: ExtractionResult
    ) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO document_extraction_sections VALUES (?, ?, ?, ?)",
                (document_id, cache_key, index, result.model_dump_json()),
            )

    def finish(self, document_id: str, cache_key: str, result: ExtractionResult) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "UPDATE document_extractions SET status = 'complete', result_json = ?, "
                "error = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE document_id = ? AND cache_key = ?",
                (result.model_dump_json(), document_id, cache_key),
            )

    def fail(self, document_id: str, cache_key: str, error: str) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "UPDATE document_extractions SET status = 'failed', result_json = NULL, "
                "error = ?, updated_at = CURRENT_TIMESTAMP WHERE document_id = ? AND cache_key = ?",
                (error, document_id, cache_key),
            )
