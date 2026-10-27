"""Shared controlled extraction fixtures; no credentials, network, or real SEC claims."""

import pytest
from document_fixtures import (  # noqa: F401
    document_service_factory,
    generation_response,
    synthetic_records,
)
from pydantic_ai import models

from credit_monitoring.domain import SourceEvidence

models.ALLOW_MODEL_REQUESTS = False


def pytest_addoption(parser):
    parser.addoption(
        "--conversation-logfire",
        action="store_true",
        help="Export synthetic telemetry from the five-turn conversation test to Logfire.",
    )


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    # Locally stored Logfire credentials must never enable export in ordinary tests.
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")


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
