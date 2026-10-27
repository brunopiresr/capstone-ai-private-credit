"""Use the same controlled document fixtures as the application tests."""

import sys
from pathlib import Path

import pytest
from pydantic_ai import models

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))

from document_fixtures import (  # noqa: E402, F401
    document_service_factory,
    generation_response,
    synthetic_records,
)


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
