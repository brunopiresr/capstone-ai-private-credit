"""Working source catalog, explicit borrower links, and maintenance operation history."""

import json
from pathlib import Path

from credit_monitoring.domain.analytics_base import new_identifier, utc_now
from credit_monitoring.persistence.database import open_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS working_documents (
    document_id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json))
);
CREATE TABLE IF NOT EXISTS document_links (
    document_id TEXT NOT NULL REFERENCES working_documents(document_id),
    borrower_id TEXT NOT NULL,
    PRIMARY KEY (document_id, borrower_id)
);
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
    owner TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome_json TEXT NOT NULL CHECK(json_valid(outcome_json))
);
"""


class DocumentWorkspaceRepository:
    def __init__(self, database_path: Path, *, process_id: str):
        self.database_path = Path(database_path)
        self.process_id = process_id
        with open_database(self.database_path) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "UPDATE operations SET state = 'interrupted', finished_at = ? "
                "WHERE state = 'running' AND owner != ?",
                (utc_now().isoformat(), process_id),
            )

    def seed(self, records: list[dict]) -> None:
        with open_database(self.database_path) as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO working_documents VALUES (?, ?, ?)",
                [(r["document_id"], "bundled", json.dumps(r)) for r in records],
            )

    def documents(self) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM working_documents ORDER BY document_id"
            ).fetchall()
            links = connection.execute("SELECT * FROM document_links").fetchall()
        return [
            {
                **json.loads(r["metadata_json"]),
                "origin": r["origin"],
                "borrower_ids": [
                    link["borrower_id"] for link in links if link["document_id"] == r["document_id"]
                ],
            }
            for r in rows
        ]

    def register(self, record: dict, borrower_ids: list[str]) -> None:
        with open_database(self.database_path) as connection:
            if connection.execute(
                "SELECT 1 FROM working_documents "
                "WHERE json_extract(metadata_json, '$.source_url') = ?",
                (record["source_url"],),
            ).fetchone():
                raise ValueError("This URL is already registered; link the existing document.")
            connection.execute(
                "INSERT INTO working_documents VALUES (?, 'registered', ?)",
                (record["document_id"], json.dumps(record)),
            )
            connection.executemany(
                "INSERT INTO document_links VALUES (?, ?)",
                [(record["document_id"], bid) for bid in borrower_ids],
            )

    def link(self, document_id: str, borrower_ids: list[str]) -> None:
        with open_database(self.database_path) as connection:
            connection.execute("DELETE FROM document_links WHERE document_id = ?", (document_id,))
            connection.executemany(
                "INSERT INTO document_links VALUES (?, ?)",
                [(document_id, bid) for bid in borrower_ids],
            )

    def start(self, kind: str, scope: list[str]) -> str:
        operation_id = new_identifier()
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, 'running', ?, NULL, '[]')",
                (operation_id, kind, json.dumps(scope), self.process_id, utc_now().isoformat()),
            )
        return operation_id

    def progress(self, operation_id: str, outcomes: list[dict]) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "UPDATE operations SET outcome_json = ? WHERE operation_id = ?",
                (json.dumps(outcomes), operation_id),
            )

    def finish(self, operation_id: str, state: str, outcomes: list[dict]) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "UPDATE operations SET state = ?, finished_at = ?, outcome_json = ? "
                "WHERE operation_id = ?",
                (state, utc_now().isoformat(), json.dumps(outcomes), operation_id),
            )

    def operations(self) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute("SELECT * FROM operations ORDER BY rowid DESC").fetchall()
        return [
            {
                **dict(r),
                "scope": json.loads(r["scope_json"]),
                "outcomes": json.loads(r["outcome_json"]),
            }
            for r in rows
        ]
