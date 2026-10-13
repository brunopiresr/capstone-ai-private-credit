"""Shared controlled extraction fixtures; no credentials, network, or real SEC claims."""

import csv
import json
from pathlib import Path

import pytest
from model_helpers import ScriptedModel, model_response
from pydantic_ai import models

from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain import SourceEvidence
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def quiet_framework_banner(monkeypatch):
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")


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
            model=options.pop("model", ScriptedModel()),
            **options,
        )

    return make


@pytest.fixture
def generation_response():
    return lambda extraction=None, **kwargs: model_response(extraction=extraction, **kwargs)
