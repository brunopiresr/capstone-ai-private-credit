"""Direct full-document extraction, persistent reuse, and independent evidence search."""

import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

from credit_monitoring.agents.prompts.extraction import EXTRACTION_PROMPT_VERSION
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
from credit_monitoring.observability.logging import log_step
from credit_monitoring.retrieval.lexical.sec import build_index, search

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
    """The application invokes processing directly and waits; no queue or worker."""

    def __init__(
        self,
        *,
        client: Any,
        source_file: Path,
        html_dir: Path,
        markdown_dir: Path,
        database_path: Path,
        model: str = "gpt-4o-mini",
        user_agent: str = "",
        converter: Any = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive.")
        self.client = client
        self.source_file = Path(source_file)
        self.html_dir = Path(html_dir).resolve()
        self.markdown_dir = Path(markdown_dir).resolve()
        self.model = model
        self.user_agent = user_agent
        self.converter = converter
        self.max_chars = max_chars
        self.repository = CovenantRepository(database_path)
        self._index = None
        self._index_key = None
        self._document_count = 0

    @property
    def configuration(self) -> dict:
        return {
            "model": self.model,
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

    def _key(self, document: dict) -> str:
        return _hash({"document": document, "configuration": self.configuration})

    def get_document_extraction(
        self, document_id: str, *, include_result: bool = True
    ) -> DocumentExtraction:
        """Inspect local source and cache without converting, downloading, or calling a model."""
        record = self.catalog_record(document_id)
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
            self.get_document_extraction(document_id, include_result=include_results)
            for document_id, record in self._catalog().items()
            if ticker is None or record.get("ticker") == ticker
        ]

    def process_document(self, document_id: str, force: bool = False) -> DocumentExtraction:
        with log_step(logger, "Process document", document_id=document_id, force=force):
            record = self.catalog_record(document_id)
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
                existing = self.get_document_extraction(document_id)
            if not force and existing.status == "complete" and existing.cache_key == key:
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
                    progress = f"{index + 1}/{len(sections)}"
                    result = saved.get(index)
                    if result is None:
                        with log_step(
                            logger,
                            "Extract section",
                            document_id=document_id,
                            section=progress,
                            model=self.model,
                            chars=section.end
                            - section.start
                            + sum(b - a for a, b in section.context),
                        ):
                            result = extract_covenants(
                                DOCUMENT_QUERY,
                                section.records(document),
                                client=self.client,
                                model=self.model,
                            )
                        with log_step(
                            logger, "Save section", document_id=document_id, section=progress
                        ):
                            self.repository.save_section(document_id, key, index, result)
                    else:
                        logger.info(
                            "Section cache hit document_id=%s section=%s", document_id, progress
                        )
                    parts.append(result.extraction)
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
            return self.get_document_extraction(document_id).model_copy(update={"cache_hit": False})

    def process_all_documents(
        self, ticker: str | None = None, *, force: bool = False
    ) -> list[DocumentExtraction]:
        """Process catalog documents sequentially, retaining per-document failures.

        Complete current results are reused unless force=True. A ticker limits
        processing to that issuer. Catalog validation errors propagate before
        any document is processed; individual errors return failed outcomes so
        subsequent documents are still attempted.
        """
        with log_step(logger, "Process all documents", ticker=ticker, force=force):
            with log_step(logger, "Load and validate catalog"):
                catalog = self._catalog()
            selected = [
                (document_id, record)
                for document_id, record in catalog.items()
                if ticker is None or record.get("ticker") == ticker
            ]
            total = len(selected)
            logger.info("Batch ready total_documents=%d ticker=%s force=%s", total, ticker, force)
            outcomes = []
            for index, (document_id, record) in enumerate(selected, start=1):
                started = perf_counter()
                logger.info(
                    "Batch document started document=%d/%d document_id=%s ticker=%s",
                    index,
                    total,
                    document_id,
                    record.get("ticker"),
                )
                try:
                    outcome = self.process_document(document_id, force=force)
                except Exception as exc:
                    outcome = DocumentExtraction(
                        document_id=document_id,
                        citation=filing_citation(record),
                        ticker=record.get("ticker") or None,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                outcomes.append(outcome)
                logger.log(
                    logging.ERROR if outcome.status == "failed" else logging.INFO,
                    "Batch document finished document=%d/%d document_id=%s status=%s "
                    "cache_hit=%s elapsed_s=%.2f",
                    index,
                    total,
                    document_id,
                    outcome.status,
                    outcome.cache_hit,
                    perf_counter() - started,
                )
            logger.info(
                "Batch summary total_documents=%d completed=%d failed=%d cache_hits=%d",
                total,
                sum(item.status == "complete" for item in outcomes),
                sum(item.status == "failed" for item in outcomes),
                sum(item.cache_hit for item in outcomes),
            )
            return outcomes

    def search_evidence(self, query: str, ticker: str | None = None) -> list[dict]:
        """Search complete local Markdown chunks; return passages, not a generated answer."""
        documents = [
            document
            for record in self._catalog().values()
            if (document := self._local_document(record)) is not None
            and document["content"].strip()
        ]
        key = _hash(documents)
        if key != self._index_key:
            chunks = []
            for document in documents:
                text = document["content"]
                for start in range(0, len(text), 3000):
                    end = min(start + 3500, len(text))
                    chunks.append(
                        {
                            **document,
                            "content": text[start:end],
                            "source_start": start,
                            "source_end": end,
                        }
                    )
            self._index = build_index(chunks)
            self._document_count = len(chunks)
            self._index_key = key
        return search(
            query,
            index=self._index,
            document_count=self._document_count,
            ticker=ticker,
        )[:10]
