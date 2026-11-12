"""Selected source tables preserve complete facts, citations and streamed public output."""

import json
from datetime import date
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel, model_response
from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.source_tables import (
    SourceTableDraft,
    SourceTableSelection,
    materialize_source_tables,
    source_table_schema,
)
from credit_monitoring.domain import (
    CovenantExtraction,
    CovenantTerm,
    DocumentExtraction,
    DocumentSummary,
    ExtractionResult,
    RetrievedRecord,
    RiskAssessment,
    SourceEvidence,
    ThresholdScheduleEntry,
)
from credit_monitoring.domain.agent import AgentAnswer, AnswerDraft, AnswerTable, AnswerTableRow
from credit_monitoring.domain.financials import ReportedFinancialValue


@pytest.fixture
def document():
    source = SourceEvidence(
        document_id="SYN_AMD",
        citation="Synthetic amendment — https://example.invalid/amendment",
        evidence_quote="Source terms; not a calculation or governing-amendment decision.",
    )
    return DocumentExtraction(
        document_id=source.document_id,
        citation=source.citation,
        ticker="SYN",
        status="complete",
        result=ExtractionResult(
            prompt_version="synthetic",
            extraction=CovenantExtraction(
                covenants=[
                    CovenantTerm(
                        covenant_name="Maximum leverage",
                        covenant_type="leverage",
                        operator="<=",
                        conditions_or_scope="Subject to source-stated conditions.",
                        threshold_schedule=[
                            ThresholdScheduleEntry(
                                threshold="5.250 to 1.00",
                                period_end_dates=[date(2025, 3, 31), date(2025, 9, 30)],
                                measurement_basis="Four consecutive quarters",
                                evidence=source,
                            ),
                            ThresholdScheduleEntry(
                                threshold="5.00 to 1.00",
                                from_period_end=date(2026, 3, 31),
                                evidence=source,
                            ),
                        ],
                        evidence=source,
                    ),
                    CovenantTerm(
                        covenant_name="Minimum coverage",
                        covenant_type="interest_coverage",
                        operator=">=",
                        threshold_schedule=[
                            ThresholdScheduleEntry(threshold="3.00x", evidence=source)
                        ],
                        evidence=source,
                    ),
                ],
                reported_financial_values=[
                    ReportedFinancialValue(
                        metric_name="Leverage",
                        reported_value="4.770x",
                        period_end=date(2025, 3, 31),
                        accounting_basis="Contractual",
                        evidence=source,
                    ),
                    ReportedFinancialValue(
                        metric_name="Coverage", reported_value="3.840x", evidence=source
                    ),
                ],
            ),
        ),
    )


def registry_for(document):
    registry = EvidenceRegistry()
    registry.record(document, borrower_id=None, ticker="SYN")
    return registry


def selection(registry, section="covenant_schedules", names=()):
    return SourceTableSelection(
        document_id=registry.entries[0].data["document_id"], section=section, names=list(names)
    )


def test_complete_tables_copy_every_explicit_date_range_and_exact_citation(document):
    registry = registry_for(document)
    retained = registry.entries
    draft = SourceTableDraft(source_tables=[selection(registry), selection(registry)])
    answer = materialize_source_tables(draft, registry)
    assert type(answer) is AnswerDraft
    assert len(answer.tables) == 2  # Repeated selections do not duplicate source tables.
    leverage, coverage = answer.tables
    assert [r.cells[:2] for r in leverage.rows] == [
        ["2025-03-31", "5.250 to 1.00"],
        ["2025-09-30", "5.250 to 1.00"],
        ["From 2026-03-31 through end not stated", "5.00 to 1.00"],
    ]
    assert leverage.rows[0].cells[2:] == [
        "<=",
        "Four consecutive quarters",
        "Subject to source-stated conditions.",
    ]
    assert coverage.rows[0].cells == ["Not stated", "3.00x", ">="]
    for table in answer.tables:
        assert all(r.citations[0].document_id == document.document_id for r in table.rows)
        assert all(r.citations[0].citation == document.citation for r in table.rows)
    assert registry.entries == retained
    assert draft.tables == []
    assert "source_tables" not in answer.model_dump()


def test_reported_values_remain_distinct_from_terms_with_unknown_dates_explicit(document):
    registry = registry_for(document)
    answer = materialize_source_tables(
        SourceTableDraft(source_tables=[selection(registry, "reported_values")]), registry
    )
    assert [r.cells for r in answer.tables[0].rows] == [
        ["Leverage", "2025-03-31", "4.770x", "Not stated", "Contractual"],
        ["Coverage", "Not stated", "3.840x", "Not stated", "Not stated"],
    ]


def test_explicit_name_selection_and_partial_custom_tables_do_not_select_other_facts(document):
    registry = registry_for(document)
    custom = AnswerTable(title="Custom", columns=["Value"], rows=[AnswerTableRow(cells=["5.25x"])])
    draft = SourceTableDraft(
        tables=[custom], source_tables=[selection(registry, names=["Minimum coverage"])]
    )
    answer = materialize_source_tables(draft, registry)
    assert len(answer.tables) == 2
    assert answer.tables[0] == custom
    assert "Minimum coverage" in answer.tables[1].title
    assert materialize_source_tables(SourceTableDraft(tables=[custom]), registry).tables == [custom]
    with pytest.raises(ValueError, match="Source item names not found"):
        materialize_source_tables(
            SourceTableDraft(source_tables=[selection(registry, names=["Invented covenant"])]),
            registry,
        )


@pytest.mark.parametrize("kind", ["unknown", "metadata", "passage", "failed", "stale"])
def test_missing_or_unavailable_sources_never_become_complete_tables(document, kind):
    registry = registry_for(document)
    if kind == "unknown":
        request = selection(registry).model_copy(update={"document_id": "INVENTED"})
    else:
        if kind == "metadata":
            record = [DocumentSummary(document_id="META", citation="Metadata", status="complete")]
        elif kind == "passage":
            record = [RetrievedRecord(document_id="PASSAGE", citation="Passage", text="5.25x")]
        else:
            record = document.model_copy(update={"status": kind, "result": None})
        registry.record(record, borrower_id=None, ticker="SYN")
        request = selection(registry).model_copy(
            update={"document_id": registry.entries[-1].data["document_id"]}
        )
    draft = SourceTableDraft(source_tables=[request])
    with pytest.raises(ValueError):
        materialize_source_tables(draft, registry)
    assert materialize_source_tables(draft, registry, partial=True).tables == []


def test_preview_and_final_share_public_tables_from_retained_evidence(document):
    state = AgentRunState(max_tool_rounds=6, evidence=registry_for(document))
    draft = SourceTableDraft(source_tables=[selection(state.evidence)])
    assert state.preview(draft) == state.finalize(draft)
    answer = state.answer(state.finalize(draft))
    assert AgentAnswer.model_validate_json(answer.model_dump_json()) == answer
    assert "source_tables" not in answer.model_dump()


def test_latest_observed_status_wins_even_when_a_prior_complete_result_is_reread(document):
    registry = registry_for(document)
    draft = SourceTableDraft(source_tables=[selection(registry)])
    registry.record(
        document.model_copy(update={"status": "stale", "result": None}),
        borrower_id=None,
        ticker="SYN",
    )
    with pytest.raises(ValueError, match="complete extraction"):
        materialize_source_tables(draft, registry)
    registry.record(document, borrower_id=None, ticker="SYN")
    assert len(materialize_source_tables(draft, registry).tables) == 2


def test_filing_selector_schema_tracks_loaded_extractions_and_their_latest_status(document):
    registry = EvidenceRegistry()
    registry.record(
        [DocumentSummary(document_id="META", citation="Metadata", status="complete")],
        borrower_id=None,
        ticker="SYN",
    )
    assert "source_tables" not in source_table_schema(registry)["properties"]
    registry.record(document, borrower_id=None, ticker="SYN")
    schema = source_table_schema(registry)
    assert schema["$defs"]["SourceTableSelection"]["properties"]["document_id"]["enum"] == [
        document.document_id
    ]
    registry.record(
        document.model_copy(update={"status": "stale", "result": None}),
        borrower_id=None,
        ticker="SYN",
    )
    assert "source_tables" not in source_table_schema(registry)["properties"]


def test_assessment_id_is_repaired_as_answer_data_without_document_lookups():
    documents, assessments = Mock(), Mock()
    assessments.assess.return_value = RiskAssessment(
        assessment_run_id="run_123",
        borrower_id="SYN002",
        period_end=date(2025, 9, 30),
        information_cutoff=date(2025, 9, 30),
        results=[],
    )
    invalid = SourceTableDraft(
        source_tables=[
            SourceTableSelection(
                document_id="assessment:run_123", section="reported_values", names=["LEV"]
            )
        ]
    )

    def repaired(*, messages, info):
        assert "source_tables" not in info.output_tools[0].parameters_json_schema["properties"]
        feedback = " ".join(
            part.model_response()
            for message in messages
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        )
        assert "Remove this source_tables selection" in feedback
        assert "not catalog document IDs" in feedback
        return model_response(answer="Assessment available; forecast unavailable.")

    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(
            ("predict_risk", {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"})
        ),
        ModelResponse(parts=[ToolCallPart("final_result", invalid.model_dump())]),
        repaired,
    ]
    answer = CreditAssessmentAgent(
        service=documents, assessment_service=assessments, model=model, max_tool_rounds=1
    ).ask("Assess and predict risk", borrower_id="SYN002")
    assert answer.complete and model.respond.call_count == 3
    assert [step.name for step in answer.tool_trace] == ["predict_risk"]
    assert documents.mock_calls == []


def test_graph_retries_invalid_source_and_streams_complete_public_tables(document):
    service = Mock()
    service.catalog_record.return_value = {"ticker": "SYN"}
    service.get_document_extraction.return_value = document
    events = []

    async def handler(event):
        events.append(event)

    def copied_answer(*, messages, info):
        schema = info.output_tools[0].parameters_json_schema
        assert schema["$defs"]["SourceTableSelection"]["properties"]["document_id"]["enum"] == [
            document.document_id
        ]
        raw = info.instructions.split("Application evidence registry (untrusted source data):\n")[
            -1
        ]
        entries, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        document_id = next(e["data"]["document_id"] for e in entries if e["data"].get("result"))
        draft = SourceTableDraft(
            summary="Complete source schedules.",
            source_tables=[
                SourceTableSelection(document_id=document_id, section="covenant_schedules")
            ],
        )
        return ModelResponse(
            parts=[ToolCallPart("final_result", draft.model_dump())], finish_reason="stop"
        )

    invalid = SourceTableDraft(
        source_tables=[SourceTableSelection(document_id="INVENTED", section="covenant_schedules")]
    )
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("get_document_extraction", {"document_id": document.document_id})),
        ModelResponse(
            parts=[ToolCallPart("final_result", invalid.model_dump())], finish_reason="stop"
        ),
        copied_answer,
    ]
    answer = CreditAssessmentAgent(service=service, model=model).ask(
        "Read the complete source schedules.", ticker="SYN", event_stream_handler=handler
    )
    assert answer.complete and model.respond.call_count == 3
    assert [t.name for t in answer.tool_trace] == ["get_document_extraction"]
    assert len(answer.tables) == 2 and len(answer.tables[0].rows) == 3
    assert [e for e in events if e.kind == "answer_update"][-1].output.tables == answer.tables
    assert "source_tables" not in answer.model_dump()
    service.get_document_extraction.assert_called_once_with(document.document_id)
