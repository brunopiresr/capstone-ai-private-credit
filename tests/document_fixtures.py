"""Controlled local document fixtures shared by app and notebook checks."""

import csv
import json
from pathlib import Path

import pytest
from model_helpers import ScriptedModel, model_response

from credit_monitoring.application.bootstrap import create_document_service
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION


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
        return create_document_service(
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


@pytest.fixture
def synthetic_records():
    path = Path(__file__).parent / "fixtures/sec_covenant_v2/records.json"
    return json.loads(path.read_text())["records"]
