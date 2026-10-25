"""Assessment facade tracing choices with agent/settings boundaries stubbed."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel

import credit_monitoring.agents.credit_assessment as assessment_module
from credit_monitoring.agents.events import AgentEvent
from credit_monitoring.domain.agent import AgentAnswer


@pytest.mark.parametrize("tracing_enabled", [None, False, True])
@pytest.mark.parametrize("capture_content", [False, True])
def test_assessment_tracing_override_uses_central_policy_or_inherits(
    document_service_factory, monkeypatch, tracing_enabled, capture_content
):
    inherited = object()
    explicit_settings = object()
    native_agent = SimpleNamespace(
        instrument=inherited,
        output_validator=lambda validator: validator,
    )
    settings = Mock(return_value=explicit_settings)
    policy = Mock(return_value=capture_content)
    monkeypatch.setattr(assessment_module, "Agent", Mock(return_value=native_agent))
    monkeypatch.setattr(assessment_module, "InstrumentationSettings", settings)
    monkeypatch.setattr(assessment_module, "capture_content_enabled", policy)
    monkeypatch.setattr("credit_monitoring.observability.configuration._configured", False)

    async def run_stream(agent, *args, **kwargs):
        assert agent is native_agent
        yield AgentEvent(
            kind="run_end", agent_name="Synthetic agent", answer=AgentAnswer(answer="Complete")
        )

    monkeypatch.setattr(assessment_module, "run_stream", run_stream)
    facade = assessment_module.CreditAssessmentAgent(
        service=document_service_factory(),
        model=ScriptedModel(),
        tracing_enabled=tracing_enabled,
    )
    assert facade.ask("Explain").complete
    if tracing_enabled is True:
        assert native_agent.instrument is explicit_settings
        settings.assert_called_once_with(
            include_content=capture_content, include_binary_content=False
        )
        policy.assert_called_once_with()
    else:
        assert native_agent.instrument is (inherited if tracing_enabled is None else False)
        settings.assert_not_called()
        policy.assert_not_called()
