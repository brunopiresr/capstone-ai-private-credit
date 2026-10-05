"""Direct full-document extraction, persistent reuse, and independent evidence search."""

import hashlib
import json
from pathlib import Path
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
from credit_monitoring.retrieval.lexical.sec import build_index, search

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
        record = self.catalog_record(document_id)
        text = load_markdown(
            record,
            html_dir=self.html_dir,
            markdown_dir=self.markdown_dir,
            user_agent=self.user_agent,
            converter=self.converter,
        )
        document = full_document_record(record, text, markdown_dir=self.markdown_dir)
        key = self._key(document)
        existing = self.get_document_extraction(document_id)
        if not force and existing.status == "complete" and existing.cache_key == key:
            return existing
        sections = split_document(text, max_chars=self.max_chars)
        metadata = {k: v for k, v in document.items() if k != "content"}
        self.repository.begin(
            document_id,
            key,
            metadata=metadata,
            configuration=self.configuration,
            total_sections=len(sections),
            force=force,
        )
        saved = self.repository.sections(document_id, key)
        parts = []
        try:
            for index, section in enumerate(sections):
                result = saved.get(index)
                if result is None:
                    result = extract_covenants(
                        DOCUMENT_QUERY,
                        section.records(document),
                        client=self.client,
                        model=self.model,
                    )
                    self.repository.save_section(document_id, key, index, result)
                parts.append(result.extraction)
            result = ExtractionResult(
                prompt_version=EXTRACTION_PROMPT_VERSION,
                extraction=combine_extractions(parts),
            )
            self.repository.finish(document_id, key, result)
        except Exception as exc:
            self.repository.fail(document_id, key, f"{type(exc).__name__}: {exc}")
            raise
        return self.get_document_extraction(document_id).model_copy(update={"cache_hit": False})

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
