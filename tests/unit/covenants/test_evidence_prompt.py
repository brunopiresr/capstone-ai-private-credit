"""Document prompt views preserve every explicit date without changing stored evidence."""

import json
from datetime import date

import pytest

from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.domain import (
    CovenantExtraction,
    CovenantTerm,
    DocumentExtraction,
    ExtractionResult,
    RetrievedRecord,
    SourceEvidence,
    ThresholdScheduleEntry,
)


def test_prompt_lists_all_named_dates_without_inventing_intermediate_quarters():
    source = SourceEvidence(
        document_id="SYN_AMD",
        citation="Synthetic amendment — https://example.invalid/amendment",
        evidence_quote="5.25x at March 31 and September 30, 2025; 5.00x from March 31, 2026.",
        markdown_path="/synthetic/amendment.md",
        source_start=10,
        source_end=90,
    )
    range_source = source.model_copy(update={"citation": source.citation + ", section 7"})
    document = DocumentExtraction(
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
                        conditions_or_scope="Subject to source-stated restrictions.",
                        threshold_schedule=[
                            ThresholdScheduleEntry(
                                threshold="5.25 to 1.00",
                                period_end_dates=[date(2025, 3, 31), date(2025, 9, 30)],
                                measurement_basis="Four consecutive quarters",
                                evidence=source,
                            ),
                            ThresholdScheduleEntry(
                                threshold="5.00 to 1.00",
                                from_period_end=date(2026, 3, 31),
                                evidence=range_source,
                            ),
                        ],
                        evidence=source,
                    ),
                    CovenantTerm(
                        covenant_name="Minimum interest coverage",
                        covenant_type="interest_coverage",
                        threshold_schedule=[
                            ThresholdScheduleEntry(threshold="3.00x", evidence=source)
                        ],
                        evidence=source,
                    ),
                ],
                gaps=["Other dates are not explicitly named."],
                extraction_warnings=["Unverified extraction."],
            ),
        ),
    )
    before = document.model_dump_json()
    registry = EvidenceRegistry()
    registry.record(document, borrower_id=None, ticker="SYN")
    retained = registry.entries
    view = json.loads(registry.prompt())[0]["data"]
    extraction = view["result"]["extraction"]
    leverage, coverage = extraction["covenants"]
    rows = leverage["threshold_schedule"]
    assert [row["period_end_dates"] for row in rows] == [["2025-03-31"], ["2025-09-30"], []]
    assert [row["threshold"] for row in rows] == ["5.25 to 1.00", "5.25 to 1.00", "5.00 to 1.00"]
    assert leverage["explicitly_named_period_count"] == 2
    assert all(row["measurement_basis"] == "Four consecutive quarters" for row in rows[:2])
    assert rows[2]["from_period_end"] == "2026-03-31"
    assert rows[2]["through_period_end"] is None
    assert leverage["conditions_or_scope"] == "Subject to source-stated restrictions."
    assert coverage["explicitly_named_period_count"] == 0
    assert coverage["threshold_schedule"][0]["period_end_dates"] == []
    assert extraction["gaps"] == ["Other dates are not explicitly named."]
    assert extraction["extraction_warnings"] == ["Unverified extraction."]
    assert leverage["schedule_citations"][rows[0]["citation_index"]] == {
        "document_id": source.document_id,
        "citation": source.citation,
    }
    assert leverage["schedule_citations"][rows[2]["citation_index"]] == {
        "document_id": range_source.document_id,
        "citation": range_source.citation,
    }
    assert len(registry.prompt()) < len(retained[0].payload_json)
    assert document.model_dump_json() == before
    assert registry.entries == retained
    assert (
        json.loads(retained[0].payload_json)["result"]["extraction"]["covenants"][0][
            "threshold_schedule"
        ][0]["evidence"]["evidence_quote"]
        == source.evidence_quote
    )


@pytest.mark.parametrize("status", ["missing", "stale", "failed", "unavailable"])
def test_prompt_preserves_unavailable_document_states(status):
    document = DocumentExtraction(
        document_id="SYN", citation="Synthetic source", status=status, error="Source unavailable."
    )
    registry = EvidenceRegistry()
    registry.record(document, borrower_id=None, ticker=None)
    assert json.loads(registry.prompt())[0]["data"] == document.model_dump(mode="json")


def test_prompt_preserves_search_passages_and_exact_source_locators():
    record = RetrievedRecord(
        document_id="SYN",
        citation="Synthetic source",
        text="The explicitly reported leverage ratio was 4.77x.",
        markdown_path="/synthetic/filing.md",
        source_start=100,
        source_end=150,
    )
    registry = EvidenceRegistry()
    registry.record([record], borrower_id=None, ticker=None)
    assert json.loads(registry.prompt())[0]["data"] == record.model_dump(mode="json")
