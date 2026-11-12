"""Advisory requirements: absent and explicitly empty checklists have different meanings."""

import json
from datetime import date
from pathlib import Path

from credit_monitoring.domain.analytics_base import utc_now
from credit_monitoring.persistence.database import open_database

DOCUMENT_TYPES = ("Credit agreement", "Amendment", "10-Q", "10-K", "Financial statements", "Other")


class ChecklistRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        with open_database(database_path) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS v3_document_checklists (
                borrower_id TEXT NOT NULL, period_end TEXT NOT NULL,
                items_json TEXT NOT NULL CHECK(json_valid(items_json)),
                updated_at TEXT NOT NULL, PRIMARY KEY (borrower_id, period_end)
            )""")

    def load(self, borrower_id: str, period: date) -> list[dict] | None:
        with open_database(self.database_path) as connection:
            row = connection.execute(
                (
                    "SELECT items_json FROM v3_document_checklists WHERE borrower_id=? "
                    "AND period_end=?"
                ),
                (borrower_id, period.isoformat()),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, borrower_id: str, period: date, items: list[dict], catalog: list[dict]) -> None:
        """Only an explicit, correctly typed borrower link can satisfy an item."""
        records = {r["document_id"]: r for r in catalog}
        types = [item["document_type"] for item in items]
        if len(set(types)) != len(types) or set(types) - set(DOCUMENT_TYPES):
            raise ValueError("Choose each supported document type at most once.")
        clean = []
        for item in items:
            did = item.get("document_id") or None
            if did:
                record = records.get(did)
                if not record or borrower_id not in record["borrower_ids"]:
                    raise ValueError(
                        "Attach a catalog document explicitly linked to this borrower."
                    )
                if record["document_type"] != item["document_type"]:
                    raise ValueError("The attached source must match the required document type.")
            clean.append({"document_type": item["document_type"], "document_id": did})
        with open_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO v3_document_checklists VALUES (?, ?, ?, ?) "
                "ON CONFLICT(borrower_id, period_end) DO UPDATE SET "
                "items_json=excluded.items_json, updated_at=excluded.updated_at",
                (borrower_id, period.isoformat(), json.dumps(clean), utc_now().isoformat()),
            )


def document_state(record: dict | None) -> str:
    if record is None:
        return "Missing attachment"
    if record.get("format_issue"):
        return "Unsupported document"
    status = record.get("status", "pending")
    if status == "complete":
        return "Processed · inspect evidence"
    if status in {"stale", "failed", "partial", "interrupted"}:
        return f"{status.title()} processing"
    return "Processing needed"


def checklist_states(
    items: list[dict] | None, borrower_id: str, inventory: list[dict]
) -> list[dict]:
    records = {r["document_id"]: r for r in inventory}
    rows = []
    for item in items or []:
        record = records.get(item.get("document_id"))
        if record and (
            borrower_id not in record["borrower_ids"]
            or record["document_type"] != item["document_type"]
        ):
            record = None
        rows.append({**item, "state": document_state(record)})
    return rows
