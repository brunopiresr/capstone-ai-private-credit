"""Real catalog/storage, loaders, extraction caches, and safe replacement databases."""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from document_workspace_helpers import document_workspace, local_markdown
from model_helpers import model_response

from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.application.data_maintenance import recreate_database
from credit_monitoring.application.document_workspace import MAINTENANCE_LOCK
from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.persistence.analytics_repositories import (
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
)
from credit_monitoring.persistence.document_workspace_repository import DocumentWorkspaceRepository

PERIOD = date(2025, 9, 30)
CUTOFF = date(2025, 12, 31)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("Network"))
    return document_workspace(tmp_path)


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_catalog_links_are_explicit_and_registration_preserves_bundled_inputs(workspace):
    ws, model = workspace
    source = ws.data_root / "app/sec/public_sec_documents.csv"
    original = source.read_bytes()
    assert all(r["borrower_ids"] == [] for r in ws.inventory())
    assert model.respond.call_count == 0
    ws.link("DOC_ONE", ["SYN001"])
    assert ws.inventory()[0]["borrower_ids"] == ["SYN001"]
    new_id = ws.register(
        company="Another issuer",
        title="New terms",
        url="https://example.invalid/new.html",
        document_type="Credit agreement",
        document_date=PERIOD,
        borrower_ids=["SYN002"],
    )
    assert ws._record(new_id)["borrower_ids"] == ["SYN002"]
    assert source.read_bytes() == original
    assert new_id in ws.processor._catalog()
    with pytest.raises(ValueError, match="already registered"):
        ws.register(
            company="Issuer",
            title="Duplicate",
            url="https://example.invalid/new.html",
            document_type="Amendment",
            document_date=PERIOD,
            borrower_ids=[],
        )
    with pytest.raises(ValueError, match="registered borrowers"):
        ws.link("DOC_ONE", ["NOT_A_BORROWER"])
    assert model.respond.call_count == 0


def test_fetch_cache_failures_and_source_changes_preserve_submitted_report(workspace, monkeypatch):
    ws, _ = workspace
    ws.link("DOC_ONE", ["SYN001"])
    analyst = BorrowerWorkflow(ws.portfolio, ws.workflow, ws.data_root)
    assessment = analyst.assess("SYN001", PERIOD, CUTOFF)
    rid = assessment.assessment_run_id
    analyst.validate(rid, checks=(True, True, True), notes="Checked.")
    analyst.save_report(rid, text="Original decision.", submit=True)
    submitted = ws.workflow.submissions()[0]
    calls = []

    def download(url, **kwargs):
        calls.append(url)
        if url.endswith("two.html"):
            raise ValueError("Source temporarily unavailable.")
        return "<html><p>Maximum leverage covenant 4.0x.</p></html>"

    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.download_sec_filing", download)
    outcomes = ws.run_documents("Fetch", ["DOC_ONE", "DOC_TWO"])
    assert [o["status"] for o in outcomes] == ["fetched", "failed"]
    assert analyst.needs_review(rid)
    assert analyst.validation(rid) is None
    with pytest.raises(ValueError, match="Sources changed"):
        analyst.validate(rid, checks=(True, True, True), notes="Checked again.")
    assert ws.workflow.submissions()[0] == submitted
    assert next(
        e
        for e in ws.portfolio.snapshot(period_end=PERIOD, cutoff=CUTOFF)
        if e.borrower_id == "SYN001"
    ).needs_review
    cached = ws.run_documents("Fetch", ["DOC_ONE"])
    assert cached[0]["cache_hit"]
    assert len(calls) == 2
    assert ws.repository.operations()[1]["state"] == "failed"


def test_processing_reuses_caches_reports_progress_and_forces_explicitly(workspace):
    ws, model = workspace
    local_markdown(ws)
    progress = []
    first = ws.run_documents("Process", ["DOC_ONE"], progress=lambda *args: progress.append(args))
    assert first[0]["status"] == "complete" and not first[0]["cache_hit"]
    assert any(p[0].stage == "Extracting section" for p in progress)
    assert model.respond.call_count == 1
    ws.run_documents("Process", ["DOC_ONE"])
    assert model.respond.call_count == 1
    ws.run_documents("Process", ["DOC_ONE"], force=True)
    assert model.respond.call_count == 2
    archive = json.loads(ws.archive_path.read_text())
    assert archive["document_extractions"][0]["status"] == "complete"
    assert len(archive["document_extraction_sections"]) == 1


def test_failed_sections_are_retained_and_retry_uses_them(tmp_path):
    ws, model = document_workspace(tmp_path, max_chars=500)
    local_markdown(
        ws,
        text="\n\n".join(
            f"## Clause {n}\nThe maximum leverage covenant is 4.0x." for n in range(25)
        ),
    )
    model.respond.side_effect = [
        model_response(extraction=CovenantExtraction()),
        RuntimeError("Retry"),
    ]
    first = ws.run_documents("Process", ["DOC_ONE"])
    assert first[0]["status"] == "failed"
    failed = ws.processor.get_document_extraction("DOC_ONE")
    assert failed.completed_sections == 1
    before = model.respond.call_count
    model.respond.side_effect = None
    second = ws.run_documents("Process", ["DOC_ONE"])
    assert second[0]["status"] == "complete"
    assert model.respond.call_count - before == failed.total_sections - 1


def test_unsupported_sources_and_invalid_ids_do_not_fetch(workspace):
    ws, model = workspace
    did = ws.register(
        company="Issuer",
        title="PDF",
        url="https://example.invalid/source.pdf",
        document_type="Other",
        document_date=PERIOD,
        borrower_ids=[],
    )
    assert (
        "Unsupported PDF"
        in next(r for r in ws.inventory() if r["document_id"] == did)["format_issue"]
    )
    outcome = ws.run_documents("Fetch", [did])[0]
    assert outcome["status"] == "failed" and "Unsupported PDF" in outcome["error"]
    with pytest.raises(ValueError, match="filenames"):
        ws.run_documents("Fetch", ["../escape"])
    assert model.respond.call_count == 0


def test_index_rebuild_uses_complete_local_text_and_verifies_retrieval(workspace):
    ws, _ = workspace
    local_markdown(ws, text="Maximum leverage covenant is 4.0x. " * 160)
    result = ws.rebuild_index()
    assert result["documents"] == 1 and result["chunks"] >= 2
    hits = ws.processor.search_evidence("maximum leverage")
    assert hits and hits[0]["document_id"] == "DOC_ONE"
    full = ws.processor.read_source_text("DOC_ONE")
    assert hits[0]["content"] == full[hits[0]["source_start"] : hits[0]["source_end"]]
    ws.processor.evidence_search.clear()
    assert ws.processor.search_evidence("leverage")


def test_database_recreation_restores_sources_and_preserves_workflow(workspace):
    ws, _ = workspace
    analyst = BorrowerWorkflow(ws.portfolio, ws.workflow, ws.data_root)
    assessment = analyst.assess("SYN001", PERIOD, CUTOFF)
    analyst.validate(assessment.assessment_run_id, checks=(True, True, True), notes="Checked.")
    analyst.flag(
        assessment.assessment_run_id,
        category="Performance",
        severity="Medium",
        explanation="Monitor performance.",
        action="Obtain update.",
    )
    analyst.save_report(assessment.assessment_run_id, text="Retain original.", submit=True)
    frozen = ws.workflow.submissions()
    local_markdown(ws)
    ws.run_documents("Process", ["DOC_ONE"])
    for target in ("Financial database", "Extraction database", "Analytics database"):
        summary = recreate_database(ws, target)
        assert summary["records"] > 0
        assert Path(summary["backup"]).is_file()
        assert ws.workflow.submissions() == frozen
        assert ws.workflow.flags("SYN001")
    assert ws.processor.get_document_extraction("DOC_ONE").status == "complete"
    snapshot = RiskFeatureSnapshotRepository(ws.working_dir / "analytics.sqlite3").get(
        assessment.feature_snapshot.snapshot_id
    )
    prediction = RiskPredictionRepository(ws.working_dir / "analytics.sqlite3").get(
        assessment.prediction.prediction_id
    )
    assert snapshot == assessment.feature_snapshot
    assert prediction == assessment.prediction
    assert analyst.needs_review(assessment.assessment_run_id)


@pytest.mark.parametrize("failure", ["missing", "invalid", "validation"])
def test_failed_rebuild_keeps_original_database_usable(workspace, monkeypatch, failure):
    ws, _ = workspace
    target = ws.working_dir / "financials.sqlite3"
    before = fingerprint(target)
    source = ws.data_root / "app/synthetic/synthetic_quarterly_financials.csv"
    if failure == "missing":
        source.unlink()
    elif failure == "invalid":
        source.write_text("borrower_id,period_end,total_debt\nSYN001,invalid,1\n")
    else:

        def reject(*args):
            raise ValueError("Replacement rejected.")

        monkeypatch.setattr("credit_monitoring.application.data_maintenance.check_database", reject)
    with pytest.raises((ValueError, FileNotFoundError)):
        recreate_database(ws, "Financial database")
    assert fingerprint(target) == before
    assert ws.portfolio.financial_repository.get_period("SYN001", PERIOD)
    assert ws.repository.operations()[0]["state"] == "failed"


def test_invalid_extraction_archive_does_not_replace_cache(workspace):
    ws, _ = workspace
    local_markdown(ws)
    ws.run_documents("Process", ["DOC_ONE"])
    before = fingerprint(ws.processor.repository.database_path)
    ws.archive_path.write_text('{"version": 999}')
    with pytest.raises(ValueError, match="archive version"):
        recreate_database(ws, "Extraction database")
    assert fingerprint(ws.processor.repository.database_path) == before
    assert ws.processor.get_document_extraction("DOC_ONE").status == "complete"


def test_incomplete_extraction_archive_does_not_replace_cache(workspace):
    ws, _ = workspace
    local_markdown(ws)
    ws.run_documents("Process", ["DOC_ONE"])
    before = fingerprint(ws.processor.repository.database_path)
    archive = json.loads(ws.archive_path.read_text())
    archive["document_extraction_sections"] = []
    ws.archive_path.write_text(json.dumps(archive))
    with pytest.raises(ValueError, match="retain every section"):
        recreate_database(ws, "Extraction database")
    assert fingerprint(ws.processor.repository.database_path) == before


def test_operations_block_overlap_and_mark_interrupted_on_restart(workspace):
    ws, _ = workspace
    assert MAINTENANCE_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="Another document"):
            ws.run_documents("Fetch", ["DOC_ONE"])
        assert not ws.repository.operations()
    finally:
        MAINTENANCE_LOCK.release()
    ws.repository.start("Fetch documents", ["DOC_ONE"])
    same_process = DocumentWorkspaceRepository(
        ws.repository.database_path, process_id=ws.repository.process_id
    )
    assert same_process.operations()[0]["state"] == "running"
    restarted = DocumentWorkspaceRepository(ws.repository.database_path, process_id="new-process")
    assert restarted.operations()[0]["state"] == "interrupted"
