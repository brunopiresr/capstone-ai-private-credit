"""Reusable document methods wrapped as SDK tools from signatures and docstrings."""

from agents import FunctionTool, function_tool
from agents.tool_context import ToolContext
from pydantic import StrictStr

from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.common import (
    NonEmptyString,
    tool_error,
    tool_result,
    validate_call,
)
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.processing import DocumentExtraction


class DocumentTools:
    def __init__(self, service: DocumentProcessingService, *, ticker: str | None = None) -> None:
        self.service = service
        self.ticker = ticker

    @property
    def tools(self) -> list[FunctionTool]:
        return [
            function_tool(method, failure_error_function=tool_error)
            for method in (
                self.list_documents,
                self.get_document_extraction,
                self.search_evidence,
                self.process_document,
            )
        ]

    def list_documents(
        self, ctx: ToolContext[AgentRunState], ticker: StrictStr | None = None
    ) -> str:
        """Discover available documents and their processing states.

        Use this tool to obtain valid document IDs before reading extractions or
        processing documents. Catalog descriptions identify documents; they are
        not evidence of financial facts.

        Args:
            ticker: Restrict results to this catalog ticker, or None. An
                application-configured ticker takes precedence; requests for a
                different ticker are rejected.

        Returns:
            JSON containing document metadata and processing states. Extracted
            facts are excluded from this listing.
        """
        validate_call(ctx, self.list_documents)
        documents = self.service.list_document_extractions(
            ticker=self._resolve_ticker(ticker), include_results=False
        )
        return tool_result(
            [document.model_dump(mode="json", exclude={"result"}) for document in documents]
        )

    def get_document_extraction(
        self, ctx: ToolContext[AgentRunState], document_id: NonEmptyString
    ) -> str:
        """Read the stored extraction for a catalog document.

        Use a document ID obtained from list_documents. If the extraction is
        missing or stale, use process_document when current facts are needed.

        Args:
            document_id: The exact catalog document ID.

        Returns:
            JSON containing processing status, extracted facts when complete
            and current, and source citations. Other states are reported
            explicitly without supplying old facts.
        """
        validate_call(ctx, self.get_document_extraction)
        self._check_document_scope(document_id)
        document = self.service.get_document_extraction(document_id)
        return self._document_result(document)

    def search_evidence(
        self,
        ctx: ToolContext[AgentRunState],
        query: NonEmptyString,
        ticker: StrictStr | None = None,
    ) -> str:
        """Retrieve filing passages that support an analyst question.

        Use this tool for supporting source text or questions beyond stored
        facts. Read stored extractions for complete covenant schedules; search
        returns only selected passages.

        Args:
            query: The question or terms to search for in filings.
            ticker: Restrict results to this catalog ticker, or None. Requests
                outside the configured ticker scope are rejected.

        Returns:
            JSON containing matching passages, document IDs, and exact
            citations. This tool does not generate an answer.
        """
        validate_call(ctx, self.search_evidence)
        passages = self.service.search_evidence(query=query, ticker=self._resolve_ticker(ticker))
        return tool_result(
            passages,
            sources=[
                {"document_id": passage["document_id"], "citation": passage["citation"]}
                for passage in passages
            ],
        )

    def process_document(self, ctx: ToolContext[AgentRunState], document_id: NonEmptyString) -> str:
        """Extract supported facts from a complete catalog document.

        Use this when needed facts have no complete, current extraction. A
        successful current extraction is reused from cache. This tool does not
        permit forced reprocessing.

        Args:
            document_id: The exact document ID from list_documents.

        Returns:
            JSON containing processing status, extracted facts when successful,
            cache-hit information, and source citations. Processing failures
            remain explicit in the result.
        """
        validate_call(ctx, self.process_document)
        self._check_document_scope(document_id)
        document = self.service.process_document(document_id)
        return self._document_result(document)

    def _resolve_ticker(self, requested: str | None) -> str | None:
        if self.ticker and requested not in (None, self.ticker):
            raise ValueError("Tool ticker is outside the requested issuer scope.")
        return self.ticker or requested

    def _check_document_scope(self, document_id: str) -> None:
        if self.ticker:
            record = self.service.catalog_record(document_id)
            if record.get("ticker") != self.ticker:
                raise ValueError("Document is outside the requested issuer scope.")

    @staticmethod
    def _document_result(document: DocumentExtraction) -> str:
        sources = []
        if document.status == "complete":
            sources.append({"document_id": document.document_id, "citation": document.citation})
        return tool_result(document.model_dump(mode="json"), sources=sources)
