"""Local analyst decisions and immutable handoffs, separate from rebuildable analytics."""

import json
from pathlib import Path

from credit_monitoring.domain.analytics_base import new_identifier, utc_now
from credit_monitoring.persistence.database import open_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyst_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_analyst_events ON analyst_events(run_id, kind);
CREATE TABLE IF NOT EXISTS flags (
    flag_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_flags_borrower ON flags(borrower_id);
CREATE TABLE IF NOT EXISTS analyst_submissions (
    submission_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE TABLE IF NOT EXISTS source_changes (
    change_id TEXT PRIMARY KEY,
    borrower_id TEXT NOT NULL,
    document_id TEXT,
    changed_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_changes ON source_changes(borrower_id, changed_at);
CREATE TABLE IF NOT EXISTS review_notes (
    note_id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES analyst_submissions(submission_id),
    run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_review_notes ON review_notes(submission_id);
CREATE TABLE IF NOT EXISTS analysis_requests (
    request_id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES analyst_submissions(submission_id),
    run_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_analysis_requests ON analysis_requests(borrower_id, state);
CREATE TABLE IF NOT EXISTS board_reports (
    report_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL,
    parent_id TEXT REFERENCES board_reports(report_id),
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
"""


class WorkflowRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        with open_database(self.database_path) as connection:
            connection.executescript(SCHEMA)

    def source_changed(self, borrower_id: str, document_id: str | None, reason: str) -> None:
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO source_changes VALUES (?, ?, ?, ?, ?)",
                (
                    new_identifier(),
                    borrower_id,
                    document_id,
                    utc_now().isoformat(),
                    reason,
                ),
            )

    def sources_changed_since(self, borrower_id: str, created_at: str) -> bool:
        with open_database(self.database_path) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM source_changes WHERE borrower_id = ? AND changed_at > ? LIMIT 1",
                    (borrower_id, created_at),
                ).fetchone()
                is not None
            )

    def record(self, run_id: str, borrower_id: str, kind: str, payload: dict) -> dict:
        item = dict(
            event_id=new_identifier(),
            run_id=run_id,
            borrower_id=borrower_id,
            kind=kind,
            created_at=utc_now().isoformat(),
            payload=payload,
        )
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO analyst_events VALUES (?, ?, ?, ?, ?, ?)",
                (
                    *[item[k] for k in ("event_id", "run_id", "borrower_id", "kind", "created_at")],
                    json.dumps(payload, allow_nan=False),
                ),
            )
        return item

    def events(self, run_id: str, kind: str | None = None) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM analyst_events WHERE run_id = ? "
                + ("AND kind = ? " if kind else "")
                + "ORDER BY rowid DESC",
                (run_id, kind) if kind else (run_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def add_flag(self, run_id: str, borrower_id: str, payload: dict) -> str:
        flag_id = new_identifier()
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO flags VALUES (?, ?, ?, ?, ?)",
                (
                    flag_id,
                    run_id,
                    borrower_id,
                    utc_now().isoformat(),
                    json.dumps(payload, allow_nan=False),
                ),
            )
        return flag_id

    def flags(self, borrower_id: str | None = None) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM flags "
                + ("WHERE borrower_id = ? " if borrower_id else "")
                + "ORDER BY rowid DESC",
                (borrower_id,) if borrower_id else (),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def submission(self, submission_id: str) -> dict:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM analyst_submissions WHERE submission_id = ?", (submission_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Choose a saved analyst submission.")
        return self._decode(row)

    def note(self, submission: dict, payload: dict, *, resolve_ids: list[str] = ()) -> str:
        note_id = new_identifier()
        created_at = utc_now().isoformat()
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO review_notes VALUES (?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    submission["submission_id"],
                    submission["run_id"],
                    submission["borrower_id"],
                    created_at,
                    json.dumps(payload, allow_nan=False),
                ),
            )
            for flag_id in resolve_ids:
                changed = connection.execute(
                    "UPDATE flags SET payload = json_set(payload, '$.state', 'resolved', "
                    "'$.resolved_at', ?, '$.resolution_note_id', ?) "
                    "WHERE flag_id = ? AND borrower_id = ? "
                    "AND json_extract(payload, '$.state') = 'open'",
                    (created_at, note_id, flag_id, submission["borrower_id"]),
                ).rowcount
                if changed != 1:
                    raise ValueError(
                        "A selected flag changed. Reload the case before resolving it."
                    )
        return note_id

    def notes(self, borrower_id: str | None = None) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM review_notes "
                + ("WHERE borrower_id = ? " if borrower_id else "")
                + "ORDER BY rowid DESC",
                (borrower_id,) if borrower_id else (),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def add_request(self, submission: dict, payload: dict) -> str:
        request_id = new_identifier()
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO analysis_requests VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (
                    request_id,
                    submission["submission_id"],
                    submission["run_id"],
                    submission["borrower_id"],
                    utc_now().isoformat(),
                    json.dumps(payload, allow_nan=False),
                ),
            )
        return request_id

    def requests(self, borrower_id: str | None = None) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_requests "
                + ("WHERE borrower_id = ? " if borrower_id else "")
                + "ORDER BY rowid DESC",
                (borrower_id,) if borrower_id else (),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def request(self, request_id: str) -> dict:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM analysis_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Choose a saved analysis request.")
        return self._decode(row)

    def update_request(self, request: dict, state: str, payload: dict) -> None:
        with open_database(self.database_path) as connection:
            changed = connection.execute(
                "UPDATE analysis_requests SET state = ?, payload = ? "
                "WHERE request_id = ? AND state = ? AND payload = ?",
                (
                    state,
                    json.dumps(payload, allow_nan=False),
                    request["request_id"],
                    request["state"],
                    json.dumps(request["payload"], allow_nan=False),
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("This request changed. Reload it before continuing.")

    def save_board_report(self, payload: dict, *, state: str, parent_id: str | None = None) -> str:
        report_id = new_identifier()
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO board_reports VALUES (?, ?, ?, ?, ?)",
                (
                    report_id,
                    utc_now().isoformat(),
                    state,
                    parent_id,
                    json.dumps(payload, allow_nan=False),
                ),
            )
        return report_id

    def board_reports(self) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute("SELECT * FROM board_reports ORDER BY rowid DESC").fetchall()
        return [self._decode(row) for row in rows]

    def board_report(self, report_id: str) -> dict:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM board_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Saved board report was not found.")
        return self._decode(row)

    def submit(self, run_id: str, borrower_id: str, payload: dict) -> str:
        submission_id = new_identifier()
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO analyst_submissions VALUES (?, ?, ?, ?, ?)",
                (
                    submission_id,
                    run_id,
                    borrower_id,
                    utc_now().isoformat(),
                    json.dumps(payload, allow_nan=False),
                ),
            )
        return submission_id

    def submissions(self, borrower_id: str | None = None) -> list[dict]:
        with open_database(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM analyst_submissions "
                + ("WHERE borrower_id = ? " if borrower_id else "")
                + "ORDER BY rowid DESC",
                (borrower_id,) if borrower_id else (),
            ).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row) -> dict:
        return {**dict(row), "payload": json.loads(row["payload"])}
