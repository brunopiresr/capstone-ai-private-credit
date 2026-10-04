"""Deterministic provenance and structure checks against synthetic evidence only."""

import pytest

from credit_monitoring.domain import (
    CovenantExtraction,
    CovenantTerm,
    FinancialMetricDefinition,
    ThresholdScheduleEntry,
)
from credit_monitoring.verification.extraction import validate_extraction


def term_with(evidence, **kwargs):
    return CovenantTerm(
        covenant_name="Total Leverage", covenant_type="leverage", evidence=evidence, **kwargs
    )


@pytest.mark.parametrize(
    "phrase,operator,direction",
    [
        ("less than", "<", "maximum"),
        ("not exceeding", "<=", "maximum"),
        ("greater than", ">", "minimum"),
        ("at least", ">=", "minimum"),
        ("equal to", "=", "other"),
        ("Maximum Total Leverage Ratio", "<=", "maximum"),
        ("Minimum Liquidity", ">=", "minimum"),
        ("Maximum Total Leverage Ratio must be less than", "<", "maximum"),
        ("Minimum Liquidity must be greater than", ">", "minimum"),
    ],
)
def test_supported_operator_phrases(phrase, operator, direction, evidence_for):
    record = {
        "document_id": "SYN_OPERATOR",
        "citation": "Synthetic operator fixture",
        "content": f"{phrase} 5.00 to 1.00.",
    }
    extraction = CovenantExtraction(
        covenants=[
            term_with(
                evidence_for(record),
                operator=operator,
                threshold_direction=direction,
                operator_quote=phrase,
            )
        ]
    )
    report = validate_extraction(extraction, [record])
    assert report.is_valid


def test_explicit_comparison_overrides_maximum_label(evidence_for):
    record = {
        "document_id": "SYN_OPERATOR",
        "citation": "Synthetic operator fixture",
        "content": "Maximum Total Leverage Ratio must be less than 5.00 to 1.00.",
    }
    extraction = CovenantExtraction(
        covenants=[
            term_with(
                evidence_for(record),
                operator="<=",
                threshold_direction="maximum",
                operator_quote="Maximum Total Leverage Ratio must be less than",
            )
        ]
    )
    assert "operator_wording_mismatch" in {
        i.code for i in validate_extraction(extraction, [record]).issues
    }


def test_missing_operator_remains_missing(synthetic_records, evidence_for):
    extraction = CovenantExtraction(covenants=[term_with(evidence_for(synthetic_records["base"]))])
    before = extraction.model_dump_json()
    report = validate_extraction(extraction, [synthetic_records["base"]])
    assert extraction.model_dump_json() == before
    assert extraction.covenants[0].operator is None
    assert extraction.covenants[0].threshold_direction == "not_stated"
    assert "missing_operator" in {i.code for i in report.issues}


def test_direction_and_operator_quote_failures_are_reported(synthetic_records, evidence_for):
    extraction = CovenantExtraction(
        covenants=[
            term_with(
                evidence_for(synthetic_records["base"]),
                operator="<=",
                threshold_direction="minimum",
                operator_quote="invented comparison",
            )
        ]
    )
    codes = {i.code for i in validate_extraction(extraction, [synthetic_records["base"]]).issues}
    assert {"operator_direction_mismatch", "operator_quote_not_supported"} <= codes


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"document_id": "SYN_UNSUPPLIED"}, "source_pair_mismatch"),
        ({"citation": "Synthetic fixture: open"}, "source_pair_mismatch"),
        ({"evidence_quote": "Invented compliant ratio."}, "quote_not_verbatim"),
        (
            {
                "evidence_quote": "Synthetic Borrower LLC must maintain a Maximum "
                "Total Leverage Ratio!"
            },
            "quote_not_verbatim",
        ),
        ({"markdown_path": "invented.md"}, "source_metadata_mismatch"),
        ({"source_start": 0}, "source_metadata_mismatch"),
        ({"source_end": 100}, "source_metadata_mismatch"),
        ({"evidence_quote": ""}, "empty_evidence_quote"),
    ],
)
def test_wrong_or_fabricated_provenance_fails_without_mutation(
    changes,
    code,
    synthetic_records,
    evidence_for,
):
    record = synthetic_records["base"]
    evidence = evidence_for(record).model_copy(update=changes)
    extraction = CovenantExtraction(covenants=[term_with(evidence)])
    before = extraction.model_dump_json()
    report = validate_extraction(extraction, [record, synthetic_records["open"]])
    assert not report.is_valid and code in {i.code for i in report.issues}
    assert any(i.path.startswith("covenants[0].evidence") for i in report.issues if i.code == code)
    assert extraction.model_dump_json() == before


def test_missing_metadata_stays_null(synthetic_records, evidence_for):
    evidence = evidence_for(synthetic_records["base"])
    report = validate_extraction(
        CovenantExtraction(covenants=[term_with(evidence)]), [synthetic_records["base"]]
    )
    assert report.is_valid
    assert (
        evidence.markdown_path is None
        and evidence.source_start is None
        and evidence.source_end is None
    )


def test_matching_quote_and_metadata_resolve_overlapping_records(synthetic_records, evidence_for):
    first = {
        **synthetic_records["base"],
        "source_start": 0,
        "offset_coordinate_system": "selected_excerpt",
    }
    second = {**first, "source_start": 50, "content": "Overlap: " + first["content"]}
    extraction = CovenantExtraction(covenants=[term_with(evidence_for(second, first["content"]))])
    report = validate_extraction(extraction, [first, second])
    assert report.is_valid and "ambiguous_source_record" not in {i.code for i in report.issues}


def test_unresolved_overlapping_provenance_is_flagged(synthetic_records, evidence_for):
    first = synthetic_records["base"]
    second = {**first, "content": "Another excerpt: " + first["content"]}
    report = validate_extraction(
        CovenantExtraction(covenants=[term_with(evidence_for(first))]), [first, second]
    )
    assert "ambiguous_source_record" in {i.code for i in report.issues}


@pytest.mark.parametrize(
    "metadata,code",
    [
        ({"source_start": -1}, "negative_source_offset"),
        ({"source_start": 20, "source_end": 10}, "source_offset_order"),
        ({"source_start": 10, "source_end": 21, "source_length": 20}, "source_offset_bounds"),
    ],
)
def test_offsets_use_supplied_coordinate_bounds(metadata, code, synthetic_records, evidence_for):
    record = {
        **synthetic_records["base"],
        **metadata,
        "offset_coordinate_system": "selected_excerpt",
    }
    report = validate_extraction(
        CovenantExtraction(covenants=[term_with(evidence_for(record))]), [record]
    )
    assert not report.is_valid and code in {i.code for i in report.issues}


def test_reversed_range_and_unsupported_multi_source_value(synthetic_records, evidence_for):
    first, second = synthetic_records["base"], synthetic_records["open"]
    entry = ThresholdScheduleEntry(
        threshold="4.25 to 1.00",
        from_period_end="2025-09-30",
        through_period_end="2025-03-31",
        evidence=evidence_for(first),
    )
    extraction = CovenantExtraction(
        covenants=[term_with(evidence_for(first), threshold_schedule=[entry])]
    )
    report = validate_extraction(extraction, [first, second])
    assert {"date_range_order", "value_not_in_quote", "date_support_unverified"} <= {
        i.code for i in report.issues
    }


def test_assembled_multi_source_quote_is_not_verified(synthetic_records, evidence_for):
    first, second = synthetic_records["base"], synthetic_records["open"]
    combined = evidence_for(first, first["content"] + "\n" + second["content"])
    report = validate_extraction(
        CovenantExtraction(covenants=[term_with(combined)]), [first, second]
    )
    assert not report.is_valid and "quote_not_verbatim" in {i.code for i in report.issues}


def test_definition_links_are_not_auto_resolved(synthetic_records, evidence_for):
    record = synthetic_records["base"]
    extraction = CovenantExtraction(
        covenants=[
            term_with(
                evidence_for(record),
                metric_definition_name="Adjusted EBITDA",
            )
        ],
        financial_metric_definitions=[
            FinancialMetricDefinition(
                name="Consolidated EBITDA",
                evidence=evidence_for(synthetic_records["adjustments"]),
            )
        ],
    )
    report = validate_extraction(extraction, list(synthetic_records.values()))
    assert "missing_definition_target" in {i.code for i in report.issues}
    assert extraction.covenants[0].metric_definition_name == "Adjusted EBITDA"


def test_multiple_definition_versions_are_flagged(synthetic_records, evidence_for):
    extraction = CovenantExtraction(
        covenants=[
            term_with(
                evidence_for(synthetic_records["base"]),
                metric_definition_name="Consolidated EBITDA",
            )
        ],
        financial_metric_definitions=[
            FinancialMetricDefinition(
                name="Consolidated EBITDA",
                amendment_reference=ref,
                evidence=evidence_for(synthetic_records["adjustments"]),
            )
            for ref in ["First Amendment", "Second Amendment"]
        ],
    )
    report = validate_extraction(extraction, list(synthetic_records.values()))
    assert "ambiguous_definition_link" in {i.code for i in report.issues}


def test_truncation_and_source_typo_are_preserved(synthetic_records, evidence_for):
    record = {**synthetic_records["typo"], "truncated": True}
    extraction = CovenantExtraction(
        covenants=[
            term_with(
                evidence_for(record),
                threshold_schedule=[
                    ThresholdScheduleEntry(
                        threshold="$10.O million",
                        evidence=evidence_for(record),
                    )
                ],
            )
        ],
        gaps=["Truncated excerpt may omit applicability clauses."],
        extraction_warnings=["Source amount contains letter O; not corrected."],
    )
    report = validate_extraction(extraction, [record])
    assert {"truncated_source", "source_extraction_warning"} <= {i.code for i in report.issues}
    assert extraction.covenants[0].threshold_schedule[0].threshold == "$10.O million"
