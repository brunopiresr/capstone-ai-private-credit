"""Explicit document actions and safe local data maintenance for the connected app."""

import csv
import io
import json
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.application.portfolio_service import PortfolioService
from credit_monitoring.domain.analytics_base import new_identifier
from credit_monitoring.ingestion.loaders.sec import (
    load_catalog,
    load_sec_html,
    validate_document_id,
)
from credit_monitoring.persistence.database import open_database
from credit_monitoring.persistence.document_workspace_repository import DocumentWorkspaceRepository
from credit_monitoring.persistence.workflow_repository import WorkflowRepository

PROCESS_ID = new_identifier()
MAINTENANCE_LOCK = threading.Lock()
type Progress = Callable[[str, int, int, str, int, int], None]
CATALOG_FIELDS = (
    "document_id",
    "company",
    "ticker",
    "document_type",
    "document_date",
    "period_end",
    "source_url",
    "title",
    "role",
    "notes",
    "cik",
)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class DocumentWorkspace:
    def __init__(
        self,
        *,
        portfolio: PortfolioService,
        processor: DocumentProcessingService,
        repository: DocumentWorkspaceRepository,
        workflow: WorkflowRepository,
        data_root: Path,
        working_dir: Path,
    ):
        self.portfolio, self.processor = portfolio, processor
        self.repository, self.workflow = repository, workflow
        self.data_root, self.working_dir = Path(data_root), Path(working_dir)
        self.archive_path = self.processor.repository.database_path.with_suffix(".archive.json")
        source = self.data_root / "app" / "sec" / "public_sec_documents.csv"
        if source.is_file():
            records = load_catalog(source)
            for record in records:
                validate_document_id(record["document_id"])
            self.repository.seed(records)
        self.sync_catalog()

    def sync_catalog(self) -> None:
        output = io.StringIO()
        writer = csv.DictWriter(
            output, fieldnames=CATALOG_FIELDS, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(self.repository.documents())
        text = output.getvalue()
        path = self.processor.source_file
        if not path.is_file() or path.read_text() != text:
            atomic_text(path, text)

    @property
    def borrowers(self) -> dict[str, str]:
        return {b["borrower_id"]: b["borrower_name"] for b in self.portfolio.borrowers}

    @property
    def busy(self) -> bool:
        return MAINTENANCE_LOCK.locked()

    def _validate_links(self, borrower_ids: list[str]) -> list[str]:
        if set(borrower_ids) - self.borrowers.keys():
            raise ValueError("Choose registered borrowers for explicit document links.")
        return list(dict.fromkeys(borrower_ids))

    def register(
        self,
        *,
        company: str,
        title: str,
        url: str,
        document_type: str,
        document_date: date,
        borrower_ids: list[str],
        ticker: str = "",
    ) -> str:
        parsed = urlparse(url.strip())
        if not company.strip() or not title.strip() or not document_type.strip():
            raise ValueError("Supply the issuer, document title and type.")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Supply a complete HTTP or HTTPS source URL.")
        links = self._validate_links(borrower_ids)
        document_id = f"DOC_{new_identifier().replace('-', '')}"
        with self._lock():
            self.repository.register(
                {
                    "document_id": document_id,
                    "company": company.strip(),
                    "title": title.strip(),
                    "source_url": url.strip(),
                    "document_type": document_type.strip(),
                    "document_date": document_date.isoformat(),
                    "ticker": ticker.strip(),
                },
                links,
            )
            self.sync_catalog()
            for borrower in links:
                self.workflow.source_changed(borrower, document_id, "New document registered.")
        return document_id

    def link(self, document_id: str, borrower_ids: list[str]) -> None:
        record = self._record(document_id)
        links = self._validate_links(borrower_ids)
        with self._lock():
            self.repository.link(document_id, links)
            for borrower in set(links) ^ set(record["borrower_ids"]):
                self.workflow.source_changed(borrower, document_id, "Document association changed.")

    def _record(self, document_id: str) -> dict:
        validate_document_id(document_id)
        record = next(
            (r for r in self.repository.documents() if r["document_id"] == document_id), None
        )
        if record is None:
            raise ValueError("Choose a document from the working catalog.")
        return record

    @staticmethod
    def format_issue(record: dict) -> str | None:
        suffix = Path(urlparse(record["source_url"]).path).suffix.lower()
        if suffix in {".pdf", ".docx", ".doc", ".xlsx", ".csv", ".pptx", ".zip", ".png", ".jpg"}:
            return f"Unsupported {suffix[1:].upper()} source; the current pipeline processes HTML."
        return None

    def inventory(self) -> list[dict]:
        rows = []
        errors = {}
        for operation in reversed(self.repository.operations()):
            for outcome in operation["outcomes"]:
                if outcome.get("document_id"):
                    errors[outcome["document_id"]] = outcome.get("error")
        for record in self.repository.documents():
            document_id = record["document_id"]
            extraction = self.processor.get_document_extraction(document_id, include_result=False)
            rows.append(
                {
                    **record,
                    "html_available": (self.processor.html_dir / f"{document_id}.html").is_file(),
                    "markdown_available": (
                        self.processor.markdown_dir / f"{document_id}.md"
                    ).is_file(),
                    "status": extraction.status,
                    "cache_hit": extraction.cache_hit,
                    "completed_sections": extraction.completed_sections,
                    "total_sections": extraction.total_sections,
                    "error": errors.get(document_id) or extraction.error,
                    "format_issue": self.format_issue(record),
                }
            )
        return rows

    @contextmanager
    def _lock(self) -> Iterator[None]:
        if not MAINTENANCE_LOCK.acquire(blocking=False):
            raise ValueError(
                "Another document or data operation is running. Wait for it to finish."
            )
        try:
            yield
        finally:
            MAINTENANCE_LOCK.release()

    @contextmanager
    def operation(self, kind: str, scope: list[str]) -> Iterator[list[dict]]:
        with self._lock():
            operation_id = self.repository.start(kind, scope)
            outcomes = []
            try:
                yield outcomes
            except Exception as error:
                outcomes.append({"status": "failed", "error": f"{type(error).__name__}: {error}"})
                self.repository.finish(operation_id, "failed", outcomes)
                raise
            else:
                state = (
                    "failed" if any(o.get("status") == "failed" for o in outcomes) else "complete"
                )
                self.repository.finish(operation_id, state, outcomes)

    def run_documents(
        self,
        kind: str,
        document_ids: list[str],
        *,
        force: bool = False,
        progress: Progress | None = None,
    ) -> list[dict]:
        if kind not in {"Fetch", "Process"}:
            raise ValueError("Choose Fetch or Process.")
        selected = list(dict.fromkeys(document_ids))
        if not selected:
            raise ValueError("Select at least one document.")
        records = [self._record(document_id) for document_id in selected]
        with self.operation(f"{'Reprocess' if force else kind} documents", selected) as outcomes:
            operation_id = self.repository.operations()[0]["operation_id"]
            for index, record in enumerate(records, 1):
                document_id = record["document_id"]
                source_paths = [
                    self.processor.html_dir / f"{document_id}.html",
                    self.processor.markdown_dir / f"{document_id}.md",
                ]

                def source_stamp():
                    return [
                        (path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else None
                        for path in source_paths
                    ]

                before = source_stamp()

                def report(stage, done=0, total=0):
                    if progress:
                        progress(document_id, index, len(records), stage, done, total)

                report("Fetching source" if kind == "Fetch" else "Processing source")
                try:
                    if issue := self.format_issue(record):
                        raise ValueError(issue)
                    if kind == "Fetch":
                        path = self.processor.html_dir / f"{document_id}.html"
                        cache_hit = path.is_file() and bool(path.read_text().strip())
                        load_sec_html(
                            record,
                            html_dir=self.processor.html_dir,
                            user_agent=self.processor.user_agent,
                        )
                        result = {
                            "document_id": document_id,
                            "status": "fetched",
                            "cache_hit": cache_hit,
                        }
                    else:
                        extraction = self.processor.process_document(
                            document_id, force=force, progress=report
                        )
                        result = {
                            "document_id": document_id,
                            "status": extraction.status,
                            "cache_hit": extraction.cache_hit,
                            "sections": extraction.completed_sections,
                        }
                    if not result["cache_hit"]:
                        for borrower in record["borrower_ids"]:
                            self.workflow.source_changed(
                                borrower, document_id, f"{kind} completed."
                            )
                except Exception as error:
                    result = {
                        "document_id": document_id,
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                    }
                    if before != source_stamp():
                        for borrower in record["borrower_ids"]:
                            self.workflow.source_changed(
                                borrower, document_id, "Source updated; extraction needs retry."
                            )
                outcomes.append(result)
                self.repository.progress(operation_id, outcomes)
                report("Failed" if result["status"] == "failed" else "Finished", 1, 1)
            if kind == "Process":
                self.save_extraction_archive()
        return outcomes

    def save_extraction_archive(self) -> None:
        with open_database(self.processor.repository.database_path) as connection:
            archive = {
                "version": 1,
                **{
                    table: [dict(r) for r in connection.execute(f"SELECT * FROM {table}")]
                    for table in ("document_extractions", "document_extraction_sections")
                },
            }
        atomic_text(self.archive_path, json.dumps(archive, allow_nan=False))

    def local_documents(self) -> list[dict]:
        return [
            document
            for record in self.processor._catalog().values()
            if (document := self.processor._local_document(record)) and document["content"].strip()
        ]

    def rebuild_index(self, *, progress: Callable[[str], None] | None = None) -> dict:
        with self.operation("Rebuild retrieval index", ["All local Markdown"]) as outcomes:
            if progress:
                progress("Reading local document text")
            documents = self.local_documents()
            if not documents:
                raise ValueError("No local document text is available. Process a document first.")
            terms = re.findall(r"[A-Za-z]{4,}", documents[0]["content"])
            if not terms:
                raise ValueError("No searchable text is available in the local sources.")
            if progress:
                progress("Building lexical index")
            count = self.processor.evidence_search.rebuild(documents)
            if progress:
                progress("Checking source retrieval")
            hits = self.processor.evidence_search.search(documents, terms[0])
            if not hits:
                raise ValueError("The rebuilt index did not return a source passage.")
            summary = {
                "status": "complete",
                "documents": len(documents),
                "chunks": count,
                "verification_hits": len(hits),
            }
            outcomes.append(summary)
        return summary
