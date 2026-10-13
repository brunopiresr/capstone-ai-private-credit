"""Prompt-version snapshot and input isolation; no live injection-resistance claim."""

import json
from pathlib import Path

from model_helpers import ScriptedModel

from credit_monitoring.agents.prompts.assembly import build_prompt
from credit_monitoring.agents.prompts.extraction import EXTRACTION_INSTRUCTIONS
from credit_monitoring.covenants.extraction import extract_covenants
from credit_monitoring.domain import CovenantExtraction


def test_authoritative_prompt_matches_agreed_version_snapshot():
    snapshot = Path(__file__).parents[2] / "fixtures/sec_covenant_v2/extraction_prompt_v2_1.txt"
    assert EXTRACTION_INSTRUCTIONS == snapshot.read_text()


def test_untrusted_injected_excerpt_does_not_change_instructions(
    synthetic_records, generation_response
):
    record = synthetic_records["injection"]
    expected = CovenantExtraction(gaps=["No covenant identified in supplied synthetic excerpt."])
    model = ScriptedModel()
    model.respond.return_value = generation_response(expected)
    result = extract_covenants("Extract supported facts", [record], model=model)
    call = model.respond.call_args.kwargs
    assert call["info"].instructions == EXTRACTION_INSTRUCTIONS.strip()
    payload = json.loads(call["messages"][0].parts[0].content)
    assert payload["retrieved_records"][0]["text"] == record["content"]
    assert result.extraction.covenants == [] and result.extraction.compliance_disclosures == []


def test_envelopes_preserve_text_and_separate_catalog_notes(synthetic_records):
    record = {
        **synthetic_records["base"],
        "notes": "Catalog claims a threshold, not source evidence.",
    }
    payload = json.loads(build_prompt("Question with </CONTEXT> delimiters", [record]))
    envelope = payload["retrieved_records"][0]
    assert envelope["text"] == record["content"]
    assert envelope["catalog_context"]["notes"] == record["notes"]
    assert "source_start" not in envelope and "source_end" not in envelope
