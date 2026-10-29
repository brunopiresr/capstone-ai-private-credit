"""Isolated, offline evaluation app tests."""

import sys
from pathlib import Path

import pytest
from pydantic_ai import models

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def agent_calls(monkeypatch):
    from types import SimpleNamespace

    import evaluation_backend as backend

    from credit_monitoring.domain.agent import AgentAnswer

    calls = []

    def make_agent(case, folder, model, *, tracing_enabled):
        assert tracing_enabled is None

        async def ask_async(question, **kwargs):
            assert question == case["question"]
            assert kwargs["ticker"] == case["ticker"]
            assert kwargs["borrower_id"] == case["borrower_id"]
            assert set(kwargs) == {"ticker", "borrower_id", "event_stream_handler"}
            calls.append({"case_id": case["case_id"], "folder": folder, "model": model})
            return AgentAnswer(
                answer=f"Generated answer for {case['case_id']}",
                confidence="high",
                confidence_explanation="Scripted test response.",
            )

        return SimpleNamespace(ask_async=ask_async)

    monkeypatch.setattr(backend.workbench, "make_agent", make_agent)
    monkeypatch.setattr(backend, "is_observability_configured", lambda: False)
    return calls
