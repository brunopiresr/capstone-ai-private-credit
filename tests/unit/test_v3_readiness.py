"""Checklist and readiness behavior without network or generated facts."""

from datetime import date

import pytest

from credit_monitoring.web_v3.checklist import (
    ChecklistRepository,
    checklist_states,
    document_state,
)

PERIOD = date(2024, 9, 30)


def test_absent_empty_and_attached_checklists_persist(tmp_path):
    repository = ChecklistRepository(tmp_path / "workflow.sqlite3")
    assert repository.load("A", PERIOD) is None
    repository.save("A", PERIOD, [], [])
    assert ChecklistRepository(repository.database_path).load("A", PERIOD) == []
    catalog = [{"document_id": "D", "borrower_ids": ["A"], "document_type": "Credit agreement"}]
    items = [{"document_type": "Credit agreement", "document_id": "D"}]
    repository.save("A", PERIOD, items, catalog)
    assert repository.load("A", PERIOD) == items
    assert repository.load("A", date(2024, 6, 30)) is None
    assert checklist_states(items, "A", [{**catalog[0], "status": "complete"}])[0][
        "state"
    ].startswith("Processed")
    assert checklist_states(items, "A", [])[0]["state"] == "Missing attachment"
    assert checklist_states(items, "B", catalog)[0]["state"] == "Missing attachment"


@pytest.mark.parametrize(
    "record",
    [
        {"document_id": "D", "borrower_ids": ["B"], "document_type": "Credit agreement"},
        {"document_id": "D", "borrower_ids": ["A"], "document_type": "10-Q"},
    ],
)
def test_attachment_requires_explicit_link_and_type(tmp_path, record):
    repository = ChecklistRepository(tmp_path / "workflow.sqlite3")
    with pytest.raises(ValueError):
        repository.save(
            "A", PERIOD, [{"document_type": "Credit agreement", "document_id": "D"}], [record]
        )
    assert repository.load("A", PERIOD) is None


@pytest.mark.parametrize(
    "status,expected",
    [
        ("pending", "Processing needed"),
        ("failed", "Failed processing"),
        ("stale", "Stale processing"),
        ("complete", "Processed · inspect evidence"),
    ],
)
def test_document_states(status, expected):
    assert document_state({"status": status}) == expected
    assert document_state({"status": status, "format_issue": "PDF"}) == "Unsupported document"
