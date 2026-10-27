"""Narrative RAG uses injected PydanticAI models and preserves its string contract."""

import asyncio
import json
from unittest.mock import Mock

from model_helpers import ScriptedModel
from pydantic_ai.messages import ModelResponse, TextPart

from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.application.rag_service import rag, rag_async


def test_narrative_uses_centralized_evidence_only_instructions(synthetic_records):
    index = Mock()
    index.search.return_value = [synthetic_records["base"]]
    model = ScriptedModel(
        response=ModelResponse(parts=[TextPart("Synthetic cited narrative response.")])
    )
    answer = rag("Describe disclosed terms", model=model, index=index, document_count=1)
    assert answer == "Synthetic cited narrative response."
    request = model.respond.call_args.kwargs
    assert request["info"].instructions == NARRATIVE_INSTRUCTIONS.strip()
    assert (
        json.loads(request["messages"][0].parts[0].content)["retrieved_records"][0]["text"]
        == synthetic_records["base"]["content"]
    )


def test_narrative_empty_evidence_skips_model():
    model = ScriptedModel()
    assert (
        rag("Describe terms", model=model, index=None, document_count=0)
        == "No relevant evidence was retrieved."
    )
    model.respond.assert_not_called()


def test_async_narrative_empty_evidence_skips_model():
    model = ScriptedModel()
    answer = asyncio.run(rag_async("Describe terms", model=model, index=None, document_count=0))
    assert answer == "No relevant evidence was retrieved."
    model.respond.assert_not_called()
