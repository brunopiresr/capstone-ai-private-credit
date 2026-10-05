"""Shared controlled extraction fixtures; no credentials, network, or real SEC claims."""

import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from openai.types.responses import (
    ParsedResponse,
    ParsedResponseOutputMessage,
    ParsedResponseOutputText,
    ResponseOutputRefusal,
)
from openai.types.responses.response import IncompleteDetails

from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain import SourceEvidence
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION


@pytest.fixture
def synthetic_records():
    path = Path(__file__).parent / "fixtures/sec_covenant_v2/records.json"
    return json.loads(path.read_text())["records"]


@pytest.fixture
def evidence_for():
    def build(record, quote=None):
        return SourceEvidence(
            document_id=record["document_id"],
            citation=record["citation"],
            evidence_quote=quote if quote is not None else record["content"],
            markdown_path=record.get("markdown_path"),
            source_start=record.get("source_start"),
            source_end=record.get("source_end"),
        )

    return build


@pytest.fixture
def document_service_factory(tmp_path):
    """Registered local documents with real SQLite; all model calls are mocked."""

    def make(text="# Synthetic filing\n\nMaximum leverage ratio 4.00 to 1.00.\n", **options):
        markdown_dir = tmp_path / "markdown"
        markdown_dir.mkdir(exist_ok=True)
        (markdown_dir / "SYN.md").write_text(text, encoding="utf-8")
        (markdown_dir / ".SYN.conversion-version").write_text(CONVERSION_VERSION)
        catalog = tmp_path / "catalog.csv"
        record = {
            "document_id": "SYN",
            "company": "Synthetic Issuer",
            "ticker": "SYN",
            "document_type": "Amendment",
            "document_date": "2025-02-03",
            "source_url": "https://example.invalid/synthetic",
        }
        with catalog.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(record))
            writer.writeheader()
            writer.writerow(record)
        return DocumentProcessingService(
            source_file=catalog,
            html_dir=tmp_path / "html",
            markdown_dir=markdown_dir,
            database_path=tmp_path / "documents.sqlite3",
            client=options.pop("client", Mock()),
            **options,
        )

    return make


@pytest.fixture
def sdk_response():
    """Construct the installed SDK's actual types without sending a request."""

    def build(extraction=None, *, status="completed", refusal=None):
        content = []
        if refusal is not None:
            content.append(ResponseOutputRefusal(type="refusal", refusal=refusal))
        elif extraction is not None:
            content.append(
                ParsedResponseOutputText.model_construct(
                    type="output_text",
                    text=extraction.model_dump_json(),
                    parsed=extraction,
                    annotations=[],
                    logprobs=[],
                )
            )
        return ParsedResponse.model_construct(
            id="resp_synthetic",
            status=status,
            error=None,
            incomplete_details=IncompleteDetails(reason="max_output_tokens")
            if status == "incomplete"
            else None,
            output=[
                ParsedResponseOutputMessage.model_construct(
                    type="message",
                    id="msg_synthetic",
                    role="assistant",
                    status="completed",
                    content=content,
                )
            ],
        )

    return build
