"""Reusable document methods wrapped as PydanticAI tools from signatures and docstrings."""

from pydantic import StrictStr
from pydantic_ai import Tool

from credit_monitoring.agents.tools.common import (
    InvalidToolArguments,
    NonEmptyString,
    domain_tool,
)
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.documents import RetrievedRecord
from credit_monitoring.domain.processing import DocumentExtraction, DocumentSummary


class DocumentTools:
    def __init__(
        self,
        service: DocumentProcessingService,
        *,
        ticker: str | None = None,
    ) -> None:
        self.service = service
        self.ticker = ticker

    @property
    def tools(self) -> list[Tool]:
        return [
            domain_tool(method)
            for method in (
                self.list_documents,
                self.get_document_extraction,
                self.search_evidence,
                self.process_document,
            )
        ]

    def list_documents(self, ticker: StrictStr | None = None) -> list[DocumentSummary]:
        """Discover catalog documents, including unprocessed ones, and processing states.

        Useful when document IDs are not yet known; known catalog IDs can be read directly.

        Args:
            ticker: Catalog ticker, or None; other configured-scope tickers are rejected.

        Returns:
            Metadata and processing states without extraction payloads.
        """
        documents = self.service.list_document_extractions(
            ticker=self._resolve_ticker(ticker), include_results=False
        )
        return [DocumentSummary.from_extraction(document) for document in documents]

    def get_document_extraction(self, document_id: NonEmptyString) -> DocumentExtraction:
        """Read stored complete covenant terms and fiscal-quarter schedules with processing status.

        If missing, stale, failed or unavailable, use process_document when facts are needed.
        For complete schedules, include every requested covenant's threshold_schedule.
        An entry can contain several period_end_dates: retain every date, not just the
        first or last. Preserve stated ranges and thereafter terms too.

        Args:
            document_id: The exact catalog document ID.

        Returns:
            Status, complete current facts and citations; other states exclude old facts.
        """
        self._check_document_scope(document_id)
        return self.service.get_document_extraction(document_id)

    def search_evidence(
        self,
        query: NonEmptyString,
        ticker: StrictStr | None = None,
    ) -> list[RetrievedRecord]:
        """Retrieve supporting filing passages and evidence beyond stored facts.

        Search returns selected passages; use stored extractions for complete schedules.

        Args:
            query: Question or terms to search for in filings.
            ticker: Catalog ticker, or None; requests outside configured scope are rejected.

        Returns:
            Passages with document IDs and exact citations.
        """
        passages = self.service.search_evidence(query=query, ticker=self._resolve_ticker(ticker))
        return [RetrievedRecord.from_record(passage) for passage in passages]

    def process_document(self, document_id: NonEmptyString) -> DocumentExtraction:
        """Process the entire catalog document when needed facts lack a current extraction.

        Reuse successful current extractions from cache; forced reprocessing is unavailable.

        Args:
            document_id: The exact document ID from list_documents.

        Returns:
            Status, extracted facts, cache-hit information and citations; failures stay explicit.
        """
        self._check_document_scope(document_id)
        return self.service.process_document(document_id)

    def _resolve_ticker(self, requested: str | None) -> str | None:
        if self.ticker and requested not in (None, self.ticker):
            self._reject_scope()
        return self.ticker or requested

    def _check_document_scope(self, document_id: str) -> None:
        if self.ticker:
            record = self.service.catalog_record(document_id)
            if record.get("ticker") != self.ticker:
                self._reject_scope()

    def _reject_scope(self) -> None:
        raise InvalidToolArguments("Document or ticker is outside the configured issuer scope.")
