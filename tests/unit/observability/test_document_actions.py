"""Local document actions emit correlated spans and logs without model or network calls."""

import logging
from uuid import uuid4

import logfire
import pytest
from document_workspace_helpers import document_workspace, local_markdown
from logfire.testing import SimpleSpanProcessor, TestExporter

from credit_monitoring.application.data_maintenance import recreate_database
from credit_monitoring.observability import configuration


@pytest.fixture
def telemetry(tmp_path, monkeypatch, caplog):
    exporter = TestExporter()
    sdk = logfire.configure(
        local=True,
        send_to_logfire=False,
        console=False,
        metrics=False,
        scrubbing=logfire.ScrubbingOptions(callback=configuration._scrub_session_id),
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    monkeypatch.setattr(configuration, "logfire", sdk)
    monkeypatch.setattr(configuration, "_configured", True)
    monkeypatch.setattr(logging.getLogger("credit_monitoring"), "propagate", True)
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    workspace, _ = document_workspace(tmp_path)
    yield workspace, exporter, caplog
    sdk.shutdown()


@pytest.mark.parametrize("query, passages", [("leverage", 1), ("nonexistentword", 0)])
def test_search_logs_result_counts_and_browser_session_without_content(telemetry, query, passages):
    workspace, exporter, caplog = telemetry
    local_markdown(workspace, text="Maximum leverage covenant. PRIVATE SOURCE TEXT")
    session_id = str(uuid4())
    with logfire.set_baggage(**{"session.id": session_id}):
        assert len(workspace.processor.search_evidence(query)) == passages
    spans = exporter.exported_spans_as_dict()
    search = next(s for s in spans if s["name"] == "Search evidence")
    assert search["attributes"]["session.id"] == session_id
    assert search["attributes"]["query_length"] == len(query)
    result = next(
        r for r in caplog.records if getattr(r, "operation", "") == "evidence.search.results"
    )
    assert result.outputs == {"documents": 1, "passages": passages}
    assert "Search evidence started" in caplog.text
    assert "Search evidence complete" in caplog.text
    assert "PRIVATE SOURCE TEXT" not in str(spans) + caplog.text


@pytest.mark.parametrize(
    "target, span_name, event",
    [
        ("Retrieval index", "Rebuild retrieval index", "evidence.index.rebuilt"),
        ("Financial database", "Recreate database", "database.rebuilt"),
    ],
)
def test_rebuild_logs_success_with_counts_and_browser_session(telemetry, target, span_name, event):
    workspace, exporter, caplog = telemetry
    local_markdown(workspace)
    session_id = str(uuid4())
    with logfire.set_baggage(**{"session.id": session_id}):
        summary = (
            workspace.rebuild_index()
            if target == "Retrieval index"
            else recreate_database(workspace, target)
        )
    rebuild = next(s for s in exporter.exported_spans_as_dict() if s["name"] == span_name)
    assert rebuild["attributes"]["session.id"] == session_id
    record = next(r for r in caplog.records if getattr(r, "operation", "") == event)
    assert record.outputs == summary
    assert f"{span_name} started" in caplog.text
    assert f"{span_name} complete" in caplog.text
    assert workspace.repository.operations()[0]["state"] == "complete"


@pytest.mark.parametrize(
    "target, span_name",
    [
        ("Search evidence", "Search evidence"),
        ("Retrieval index", "Rebuild retrieval index"),
        ("Financial database", "Recreate database"),
        ("Extraction database", "Recreate database"),
        ("Analytics database", "Recreate database"),
    ],
)
def test_action_failure_is_logged_and_traced(telemetry, monkeypatch, target, span_name):
    workspace, exporter, caplog = telemetry
    if target == "Search evidence":

        def fail(*args):
            raise ValueError("Retrieval failed")

        monkeypatch.setattr(workspace.processor.evidence_search, "search", fail)
    elif target == "Financial database":
        (workspace.data_root / "app/synthetic/synthetic_quarterly_financials.csv").unlink()
    with pytest.raises(ValueError):
        if target == "Search evidence":
            workspace.processor.search_evidence("leverage")
        elif target == "Retrieval index":
            workspace.rebuild_index()
        else:
            recreate_database(workspace, target)
    action = next(s for s in exporter.exported_spans_as_dict() if s["name"] == span_name)
    assert any(e["name"] == "exception" for e in action["events"])
    assert f"{span_name} failed" in caplog.text
    assert "elapsed_s=" in caplog.text and "error_type=ValueError" in caplog.text
    if target != "Search evidence":
        assert workspace.repository.operations()[0]["state"] == "failed"
