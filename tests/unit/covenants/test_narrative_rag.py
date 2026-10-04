"""Narrative RAG dependency wiring and empty-evidence behavior; no model requests."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from credit_monitoring.agents.prompts.narrative import NARRATIVE_INSTRUCTIONS
from credit_monitoring.application.rag_service import rag


def test_narrative_uses_centralized_evidence_only_instructions(synthetic_records):
    index, client = Mock(), Mock()
    index.search.return_value = [synthetic_records["base"]]
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text="Synthetic cited narrative response."
    )
    answer = rag("Describe disclosed terms", client=client, index=index, document_count=1)
    assert answer == "Synthetic cited narrative response."
    request = client.responses.create.call_args.kwargs
    assert request["instructions"] == NARRATIVE_INSTRUCTIONS
    assert (
        json.loads(request["input"])["retrieved_records"][0]["text"]
        == synthetic_records["base"]["content"]
    )


def test_narrative_empty_evidence_skips_model():
    client = Mock()
    assert (
        rag("Describe terms", client=client, index=None, document_count=0)
        == "No relevant evidence was retrieved."
    )
    client.responses.create.assert_not_called()
