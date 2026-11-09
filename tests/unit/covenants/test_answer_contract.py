"""Claims are checked against actual evidence, including after co-emitted tools."""

import asyncio
import json

import pytest
from model_helpers import ScriptedModel, filing_answer, model_response, scripted_responses
from pydantic import ValidationError

from credit_monitoring.agents.answer_contract import finalize_content, validate_claim
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.agents.request_policy import resolve_request
from credit_monitoring.domain.agent import AgentAnswer, AnswerContent, MaterialClaim
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.evaluation.agent_batch import SUITE


@pytest.fixture
def calculation_evidence():
    raw = json.loads((SUITE / "results/2026-11-09-baseline/cases/H01/answer.json").read_text())
    outcome = RiskAssessment.model_validate(raw["tool_trace"][-1]["outcome"])
    registry = EvidenceRegistry()
    registry.record(outcome, borrower_id="SYN001", ticker=None)
    entry = next(
        e for e in registry.entries if e.kind == "calculation" and e.period_end == "2025-09-30"
    )
    context = resolve_request(
        "Assess. Reporting date: 2025-09-30. Information cutoff: 2025-09-30",
        borrower_id="SYN001",
        ticker=None,
    )
    return registry, entry, context, outcome


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_ids": []},
        {"evidence_ids": ["invented"]},
        {"borrower_id": "SYN002"},
        {"period_end": "2025-06-30"},
        {"information_cutoff": "2025-12-31"},
        {"unit": "%"},
        {"value_json": "0"},
        {"field_path": "nonexistent"},
        {"statement": "This proves sound credit management"},
    ],
)
def test_invalid_fact_references_copied_values_units_and_labels_fail(calculation_evidence, changes):
    registry, entry, context, _ = calculation_evidence
    claim = MaterialClaim(
        claim_id="actual", kind="fact", evidence_ids=[entry.evidence_id], field_path="actual_value"
    )
    claim = claim.model_copy(update=changes)
    with pytest.raises(ValueError):
        validate_claim(claim, registry, context)


def test_nulls_cannot_be_copied_as_zero_and_real_id_cannot_supply_wrong_status(
    calculation_evidence,
):
    registry, entry, context, _ = calculation_evidence
    for path, copied in (
        ("resolved_covenant.reported_actual", "0"),
        ("compliance_status", '"breach"'),
        ("operator", '">="'),
        ("financial_inputs.result_basis", '"reported"'),
    ):
        with pytest.raises(ValueError):
            validate_claim(
                MaterialClaim(
                    claim_id=path,
                    kind="fact",
                    evidence_ids=[entry.evidence_id],
                    field_path=path,
                    value_json=copied,
                ),
                registry,
                context,
            )


def test_registry_is_immutable_and_csv_provenance_survives(calculation_evidence):
    registry, entry, _, _ = calculation_evidence
    with pytest.raises(ValidationError):
        entry.borrower_id = "OTHER"
    view = entry.data
    view["actual_value"] = 1000
    assert registry.get(entry.evidence_id).data["actual_value"] == 3.125
    financial = next(e for e in registry.entries if e.kind == "csv")
    assert "row " in financial.citation and financial.data["source_row"] > 0
    assert "source_hash" in entry.data["evidence"][0]


def test_current_and_historical_claims_are_cited_with_their_own_periods(calculation_evidence):
    registry, entry, context, outcome = calculation_evidence
    content = AnswerContent(
        schema_version="agent-answer-v2",
        answer="Calculation available.",
        confidence="medium",
        confidence_explanation="Source limitations.",
    )
    rendered = finalize_content(content, registry, context, {outcome.assessment_run_id})
    assert "2025-09-30" in rendered.answer and entry.data["result_id"] in rendered.answer
    assert all(claim.evidence_ids for claim in rendered.claims)
    assert "2025-06-30" in rendered.answer


def test_correct_numbers_do_not_license_unsupported_reassurance(calculation_evidence):
    registry, entry, context, _ = calculation_evidence
    claim = MaterialClaim(
        claim_id="interpretation",
        kind="narrative",
        evidence_ids=[entry.evidence_id],
        statement="This proves sound credit management.",
    )
    with pytest.raises(ValueError, match="reassurance"):
        validate_claim(claim, registry, context)


def test_late_output_validation_repairs_after_accompanying_tools(document_service_factory):
    first = model_response(("search_evidence", {"query": "leverage"}), answer="Evidence found.")
    first.parts.reverse()
    model = ScriptedModel()
    model.respond.side_effect = scripted_responses(first, filing_answer)
    answer = CreditAssessmentAgent(
        service=document_service_factory(), model=model, max_tool_rounds=1
    ).ask("Find leverage evidence", ticker="SYN")
    assert answer.complete and answer.schema_version == "agent-answer-v2"
    assert len(answer.tool_trace) == 1
    assert model.respond.call_count == 2
    assert answer.claims and answer.evidence
    assert "SYN:" in answer.answer


def test_failed_repair_preserves_actual_work_and_does_not_commit_evidence(document_service_factory):
    model = ScriptedModel()
    unsupported = model_response(answer="The threshold is 99x.")
    model.respond.side_effect = [
        model_response(("search_evidence", {"query": "leverage"})),
        unsupported,
        unsupported,
    ]
    chat = CreditAssessmentAgent(
        service=document_service_factory(), model=model
    ).start_conversation(ticker="SYN")
    answer = chat.ask("Find leverage evidence")
    assert not answer.complete and answer.error == "incomplete_answer"
    assert len(answer.tool_trace) == 1 and answer.evidence
    assert chat._evidence == [] and chat._sources == []


def test_followup_reuses_immutable_evidence_without_cross_conversation_leak(
    document_service_factory,
):
    model = ScriptedModel()
    model.respond.side_effect = scripted_responses(
        model_response(("search_evidence", {"query": "leverage"})),
        filing_answer,
        filing_answer,
    )
    agent = CreditAssessmentAgent(service=document_service_factory(), model=model)
    chat = agent.start_conversation(ticker="SYN")
    first = chat.ask("Find leverage evidence")
    first.evidence.clear()
    followup = chat.ask("Which passage supports this?")
    assert followup.complete and followup.tool_trace == [] and followup.claims
    assert agent.start_conversation(ticker="SYN")._evidence == []
    chat.close()
    assert chat._evidence == []


def test_legacy_json_loads_without_inventing_claim_links():
    legacy = AgentAnswer.model_validate_json('{"answer":"Old uncited answer","complete":true}')
    assert legacy.schema_version is None and legacy.claims == [] and legacy.evidence == []


def test_primed_snapshot_is_evidence_but_never_supplies_analyst_dates(calculation_evidence):
    _, _, _, assessment = calculation_evidence
    from unittest.mock import Mock

    service = Mock()
    model = ScriptedModel()
    chat = CreditAssessmentAgent(assessment_service=service, model=model).start_conversation(
        borrower_id=assessment.borrower_id
    )
    chat.prime_evidence(assessment)
    assert chat._evidence and not chat._dates
    result = chat.ask("Assess covenant compliance")
    assert result.complete and "Please provide" in result.answer and result.tool_trace == []
    service.assess.assert_not_called()
    model.respond.assert_not_called()


def test_cancellation_never_retains_new_registry_entries(document_service_factory):
    async def exercise():
        model = ScriptedModel(response=model_response(("search_evidence", {"query": "leverage"})))
        chat = CreditAssessmentAgent(
            service=document_service_factory(), model=model
        ).start_conversation(ticker="SYN")
        stream = chat.stream_async("Find leverage evidence")
        async for event in stream:
            if event.kind == "tool_result":
                await stream.aclose()
                break
        assert chat._evidence == [] and chat._history == []

    asyncio.run(exercise())
