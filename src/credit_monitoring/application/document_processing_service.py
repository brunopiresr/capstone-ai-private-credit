"""Direct full-document extraction, persistent reuse, and independent evidence search."""

import asyncio
import copy
import hashlib
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic_ai.models import Model

from credit_monitoring.agents.models import DEFAULT_MODEL, model_identity, resolve_model
from credit_monitoring.agents.prompts.extraction import EXTRACTION_PROMPT_VERSION
from credit_monitoring.application.document_batch import (
    DocumentBatchProgress,
    run_document_batch,
    validate_workers,
)
from credit_monitoring.covenants.assembly import combine_extractions
from credit_monitoring.covenants.extraction import extract_covenants
from credit_monitoring.covenants.repositories import CovenantRepository
from credit_monitoring.domain import ExtractionResult
from credit_monitoring.domain.processing import DocumentExtraction
from credit_monitoring.domain.validation import RESULT_SCHEMA_VERSION
from credit_monitoring.ingestion.chunking.sections import (
    DEFAULT_MAX_CHARS,
    SEGMENTATION_VERSION,
    split_document,
)
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION, load_markdown
from credit_monitoring.ingestion.loaders.sec import (
    filing_citation,
    full_document_record,
    load_catalog,
)
from credit_monitoring.observability import session_scope
from credit_monitoring.observability.logging import log_step
from credit_monitoring.persistence.locking import resource_lock
from credit_monitoring.retrieval.lexical.local import LocalEvidenceSearch

logger = logging.getLogger(__name__)

DOCUMENT_QUERY = (
    "Extract every relevant explicitly supported fact from this document section and context, "
    "including every fiscal quarter and threshold schedule. Do not restrict extraction to a "
    "question, a current period, or a selected covenant."
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class DocumentProcessingService:
    """Synchronous single-document and bounded parallel batch extraction."""

    def __init__(
        self,
        *,
        source_file: Path,
        html_dir: Path,
        markdown_dir: Path,
        repository: CovenantRepository,
        evidence_search: LocalEvidenceSearch,
        model: Model | str = DEFAULT_MODEL,
        user_agent: str = "",
        converter: Any = None,
        max_chars: int = DEFAULT_MAX_CHARS,
        model_factory: Callable[[], Model] | None = None,
        converter_factory: Callable[[], Any] | None = None,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive.")
        self.source_file = Path(source_file)
        self.html_dir = Path(html_dir).resolve()
        self.markdown_dir = Path(markdown_dir).resolve()
        self.model = model
        self.user_agent = user_agent
        self.converter = converter
        self.max_chars = max_chars
        self.repository = repository
        self.evidence_search = evidence_search
        self.model_factory = model_factory
        self.converter_factory = converter_factory
        self._configuration_snapshot = None

    @property
    def configuration(self) -> dict:
        if self._configuration_snapshot is not None:
            return self._configuration_snapshot
        return {
            "model": model_identity(self.model),
            "schema_version": RESULT_SCHEMA_VERSION,
            "prompt_version": EXTRACTION_PROMPT_VERSION,
            "segmentation_version": SEGMENTATION_VERSION,
            "conversion_version": CONVERSION_VERSION,
            "max_chars": self.max_chars,
        }

    def _catalog(self) -> dict[str, dict]:
        catalog = {}
        for record in load_catalog(self.source_file):
            required = ("document_id", "company", "document_type", "source_url")
            if any(not isinstance(record.get(k), str) or not record[k].strip() for k in required):
                raise ValueError(f"Catalog rows require nonempty fields: {', '.join(required)}")
            document_id = record["document_id"]
            # Validate IDs before any loader constructs paths or downloads sources.
            full_document_record(record, "", markdown_dir=self.markdown_dir)
            if document_id in catalog:
                raise ValueError(f"Duplicate catalog document ID: {document_id}")
            catalog[document_id] = record
        return catalog

    def catalog_record(self, document_id: str) -> dict:
        try:
            return self._catalog()[document_id]
        except KeyError as exc:
            raise ValueError(f"Unknown catalog document: {document_id}") from exc

    def _local_document(self, record: dict) -> dict | None:
        path = self.markdown_dir / f"{record['document_id']}.md"
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        return full_document_record(record, text, markdown_dir=self.markdown_dir)

    def read_source_text(self, document_id: str) -> str:
        """Read catalog-validated Markdown without downloads, conversion, or extraction."""
        record = self.catalog_record(document_id)
        return (self.markdown_dir / f"{record['document_id']}.md").read_text(encoding="utf-8")

    def _key(self, document: dict) -> str:
        # Adding optional catalog columns must not invalidate unchanged legacy
        # extractions merely because the new fields are empty on old sources.
        optional_metadata = {
            "accession_number",
            "filing_index_url",
            "html_identified_via",
            "link_verified_as_of",
            "selection_note",
            "reference_ticker",
        }
        identity = {k: v for k, v in document.items() if k not in optional_metadata or v}
        return _hash({"document": identity, "configuration": self.configuration})

    def get_document_extraction(
        self, document_id: str, *, include_result: bool = True
    ) -> DocumentExtraction:
        """Inspect local source and cache without converting, downloading, or calling a model."""
        record = self.catalog_record(document_id)
        return self._get_document_extraction(record, include_result=include_result)

    def _get_document_extraction(self, record, *, include_result=True) -> DocumentExtraction:
        document_id = record["document_id"]
        outcome = DocumentExtraction(
            document_id=document_id,
            citation=filing_citation(record),
            ticker=record.get("ticker") or None,
            status="missing",
        )
        document = self._local_document(record)
        if document is None or not document["content"].strip():
            return outcome.model_copy(
                update={
                    "status": "unavailable",
                    "error": "Local Markdown is absent or empty; process document.",
                }
            )
        marker = self.markdown_dir / f".{document_id}.conversion-version"
        if not marker.is_file() or marker.read_text(encoding="utf-8") != CONVERSION_VERSION:
            return outcome.model_copy(
                update={
                    "status": "stale",
                    "error": "Markdown conversion marker is outdated; process document.",
                }
            )
        key = self._key(document)
        row = self.repository.get(document_id, key)
        if row is None:
            status = "stale" if self.repository.has_document(document_id) else "missing"
            return outcome.model_copy(update={"status": status, "cache_key": key})
        result = (
            ExtractionResult.model_validate_json(row["result_json"])
            if include_result and row["status"] == "complete" and row["result_json"]
            else None
        )
        return outcome.model_copy(
            update={
                "status": row["status"],
                "cache_key": key,
                "result": result,
                "cache_hit": row["status"] == "complete" and row["result_json"] is not None,
                "error": row["error"],
                "total_sections": row["total_sections"],
                "completed_sections": self.repository.section_count(document_id, key),
            }
        )

    def list_document_extractions(
        self, ticker: str | None = None, *, include_results: bool = True
    ) -> list[DocumentExtraction]:
        """Include unprocessed catalog documents, not just completed database rows."""
        return [
            self._get_document_extraction(record, include_result=include_results)
            for document_id, record in self._catalog().items()
            if ticker is None or record.get("ticker") == ticker
        ]

    def process_document(
        self,
        document_id: str,
        force: bool = False,
        *,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> DocumentExtraction:
        return self._process_document_record(self.catalog_record(document_id), force, progress)

    def _process_document_record(self, record, force=False, progress=None):
        with resource_lock("document", str(self.markdown_dir), record["document_id"]):
            return self._process_unlocked_record(record, force, progress)

    def _process_unlocked_record(self, record, force=False, progress=None):
        document_id = record["document_id"]
        suffix = Path(urlparse(record["source_url"]).path).suffix.lower()
        if suffix in {".pdf", ".docx", ".doc", ".xlsx", ".csv", ".pptx", ".zip", ".png", ".jpg"}:
            raise ValueError(
                f"Unsupported {suffix[1:].upper()} source; the pipeline processes HTML."
            )
        with (
            session_scope(),
            log_step(logger, "Process document", document_id=document_id, force=force),
        ):
            if progress:
                progress("Loading and converting source", 0, 0)
            with log_step(logger, "Load Markdown", document_id=document_id):
                text = load_markdown(
                    record,
                    html_dir=self.html_dir,
                    markdown_dir=self.markdown_dir,
                    user_agent=self.user_agent,
                    converter=self.converter,
                )
            with log_step(logger, "Check extraction cache", document_id=document_id):
                document = full_document_record(record, text, markdown_dir=self.markdown_dir)
                key = self._key(document)
                existing = self._get_document_extraction(record)
            if not force and existing.status == "complete" and existing.cache_key == key:
                if progress:
                    progress(
                        "Reusing completed extraction",
                        existing.total_sections,
                        existing.total_sections,
                    )
                logger.info("Extraction cache hit document_id=%s", document_id)
                return existing
            logger.info(
                "Extraction required document_id=%s cache_status=%s force=%s",
                document_id,
                existing.status,
                force,
            )
            with log_step(
                logger,
                "Split document",
                document_id=document_id,
                chars=len(text),
                max_chars=self.max_chars,
            ):
                sections = split_document(text, max_chars=self.max_chars)
            metadata = {k: v for k, v in document.items() if k != "content"}
            with log_step(logger, "Prepare section cache", document_id=document_id):
                self.repository.begin(
                    document_id,
                    key,
                    metadata=metadata,
                    configuration=self.configuration,
                    total_sections=len(sections),
                    force=force,
                )
                saved = self.repository.sections(document_id, key)
            logger.info(
                "Sections ready document_id=%s total_sections=%d cached_sections=%d model=%s",
                document_id,
                len(sections),
                len(saved),
                self.model,
            )
            parts = []
            try:
                for index, section in enumerate(sections):
                    section_progress = f"{index + 1}/{len(sections)}"
                    if progress:
                        progress("Extracting section", index, len(sections))
                    result = saved.get(index)
                    if result is None:
                        with log_step(
                            logger,
                            "Extract section",
                            document_id=document_id,
                            section=section_progress,
                            model=model_identity(self.model),
                            chars=section.end
                            - section.start
                            + sum(b - a for a, b in section.context),
                        ):
                            result = extract_covenants(
                                DOCUMENT_QUERY,
                                section.records(document),
                                model=self.model,
                            )
                        with log_step(
                            logger,
                            "Save section",
                            document_id=document_id,
                            section=section_progress,
                        ):
                            self.repository.save_section(document_id, key, index, result)
                    else:
                        logger.info(
                            "Section cache hit document_id=%s section=%s",
                            document_id,
                            section_progress,
                        )
                    parts.append(result.extraction)
                    if progress:
                        progress("Section saved", index + 1, len(sections))
                with log_step(logger, "Combine extractions", document_id=document_id):
                    result = ExtractionResult(
                        prompt_version=EXTRACTION_PROMPT_VERSION,
                        extraction=combine_extractions(parts),
                    )
                with log_step(logger, "Save document result", document_id=document_id):
                    self.repository.finish(document_id, key, result)
            except Exception as exc:
                with log_step(logger, "Save document failure", document_id=document_id):
                    self.repository.fail(document_id, key, f"{type(exc).__name__}: {exc}")
                raise
            return self._get_document_extraction(record).model_copy(update={"cache_hit": False})

    def process_all_documents(
        self, ticker: str | None = None, *, force: bool = False, max_workers: int = 4
    ) -> list[DocumentExtraction]:
        """Validate once, then process files concurrently with stable catalog order."""
        validate_workers(max_workers)
        with session_scope(), log_step(logger, "Process all documents", ticker=ticker, force=force):
            with log_step(logger, "Load and validate catalog"):
                catalog = self._catalog()
            records = [r for r in catalog.values() if ticker is None or r.get("ticker") == ticker]
            return self._process_batch(records, force, max_workers, None)

    def process_documents(
        self,
        document_ids: list[str],
        *,
        force: bool = False,
        max_workers: int = 4,
        progress: Callable[[DocumentBatchProgress], None] | None = None,
    ) -> list[DocumentExtraction]:
        """Process explicit selections; workers never call application/UI callbacks."""
        validate_workers(max_workers)
        with session_scope(), log_step(logger, "Process selected documents", force=force):
            catalog = self._catalog()
            selected = list(dict.fromkeys(document_ids))
            if unknown := set(selected) - catalog.keys():
                raise ValueError(f"Unknown catalog documents: {sorted(unknown)}")
            return self._process_batch([catalog[k] for k in selected], force, max_workers, progress)

    def _process_batch(self, records, force, max_workers, progress):
        parallel = max_workers > 1 and len(records) > 1
        if parallel:
            if not isinstance(self.model, str) and self.model_factory is None:
                raise ValueError(
                    "Parallel injected models require model_factory; or use max_workers=1."
                )
            if self.converter is not None and self.converter_factory is None:
                raise ValueError(
                    "Parallel injected converters require converter_factory; or use max_workers=1."
                )
        isolated = parallel or self.model_factory is not None or self.converter_factory is not None

        def process(record, report):
            if isolated:
                return self._isolated_document(record, force, report)
            return self._process_document_record(record, force, report)

        return run_document_batch(records, process, max_workers=max_workers, progress=progress)

    def _isolated_document(self, record, force, progress):
        # A cache hit requires neither credentials nor constructing provider clients.
        with resource_lock("document", str(self.markdown_dir), record["document_id"]):
            if not force and self._get_document_extraction(record).cache_hit:
                return self._process_unlocked_record(record, force, progress)
            worker = copy.copy(self)
            worker._configuration_snapshot = self.configuration.copy()
            if self.model_factory is None and not isinstance(self.model, str):
                # Sequential callers may supply only a converter factory. Their
                # shared model keeps its caller-owned client and event loop.
                worker.converter = self.converter_factory()
                try:
                    return worker._process_unlocked_record(record, force, progress)
                finally:
                    if callable(getattr(worker.converter, "close", None)):
                        worker.converter.close()
            with asyncio.Runner() as runner:
                asyncio.set_event_loop(runner.get_loop())
                worker.model = (
                    self.model_factory() if self.model_factory else resolve_model(self.model)
                )
                worker.converter = None
                try:
                    runner.run(worker.model.__aenter__())
                    try:
                        if not isinstance(self.model, str) and model_identity(
                            worker.model
                        ) != model_identity(self.model):
                            raise ValueError(
                                "model_factory must preserve the configured model identity."
                            )
                        worker.converter = (
                            self.converter_factory() if self.converter_factory else None
                        )
                        return worker._process_unlocked_record(record, force, progress)
                    finally:
                        runner.run(worker.model.__aexit__(*sys.exc_info()))
                finally:
                    if worker.converter is not None and callable(
                        getattr(worker.converter, "close", None)
                    ):
                        worker.converter.close()

    def search_evidence(self, query: str, ticker: str | None = None) -> list[dict]:
        """Search complete local Markdown chunks; return passages, not a generated answer."""
        documents = [
            document
            for record in self._catalog().values()
            if (document := self._local_document(record)) is not None
            and document["content"].strip()
        ]
        return self.evidence_search.search(documents, query, ticker)
