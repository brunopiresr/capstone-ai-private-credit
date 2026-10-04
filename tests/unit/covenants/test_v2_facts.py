"""Preservation checks on expected synthetic outputs, not live model accuracy claims."""

from datetime import date

import pytest

from credit_monitoring.domain import (
    AgreementAmendment,
    ComplianceDisclosure,
    CovenantExtraction,
    CovenantTerm,
    CovenantTestingEvent,
    FinancialMetricDefinition,
    ReportedFinancialValue,
    ThresholdScheduleEntry,
)
from credit_monitoring.verification.extraction import validate_extraction


@pytest.mark.parametrize(
    "source,threshold,kwargs",
    [
        ("base", "5.00 to 1.00", {}),
        ("base", "5.00 to 1.00", {"period_end_dates": ["2025-03-31", "2025-06-30"]}),
        (
            "bounded",
            "$10.000 million",
            {"from_period_end": "2025-03-31", "through_period_end": "2025-09-30"},
        ),
        ("open", "4.25 to 1.00", {"from_period_end": "2025-09-30"}),
    ],
)
def test_threshold_schedule_preserves_only_supplied_dates(
    source,
    threshold,
    kwargs,
    synthetic_records,
    evidence_for,
):
    evidence = evidence_for(synthetic_records[source])
    entry = ThresholdScheduleEntry(threshold=threshold, evidence=evidence, **kwargs)
    assert entry.threshold == threshold
    assert entry.period_end_dates == [
        date.fromisoformat(d) for d in kwargs.get("period_end_dates", [])
    ]
    assert entry.through_period_end == (
        date.fromisoformat(kwargs["through_period_end"]) if "through_period_end" in kwargs else None
    )
    # Range endpoints never expand into intermediate quarter dates.
    if "from_period_end" in kwargs:
        assert entry.period_end_dates == []


def test_successive_amendments_and_execution_effective_dates_remain_distinct(
    synthetic_records,
    evidence_for,
):
    agreements, terms = [], []
    for key, ordinal, execution, effective, threshold in [
        ("amendment_a", "First Amendment", "2025-02-01", "2025-02-15", "5.00 to 1.00"),
        ("amendment_b", "Second Amendment", "2025-05-01", "2025-05-15", "6.00 to 1.00"),
    ]:
        evidence = evidence_for(synthetic_records[key])
        agreements.append(
            AgreementAmendment(
                agreement_name="Synthetic Credit Agreement",
                amendment_name=ordinal,
                execution_date=execution,
                stated_effective_date=effective,
                evidence=evidence,
            )
        )
        terms.append(
            CovenantTerm(
                covenant_name="Maximum Total Leverage Ratio",
                covenant_type="leverage",
                operator="<=",
                operator_quote="Maximum Total Leverage Ratio",
                threshold_direction="maximum",
                amendment_reference=ordinal,
                evidence=evidence,
                threshold_schedule=[ThresholdScheduleEntry(threshold=threshold, evidence=evidence)],
            )
        )
    extraction = CovenantExtraction(agreements=agreements, covenants=terms)
    assert validate_extraction(
        extraction, [synthetic_records[k] for k in ["amendment_a", "amendment_b"]]
    ).is_valid
    assert len(extraction.covenants) == 2 and extraction.conflicts == []
    assert extraction.agreements[0].execution_date != extraction.agreements[0].stated_effective_date
    assert "governing_amendment" not in extraction.model_dump()


def test_testing_events_do_not_become_actual_compliance(synthetic_records, evidence_for):
    extraction = CovenantExtraction(
        testing_events=[
            CovenantTestingEvent(
                covenant_name="Maximum Total Leverage Ratio",
                event_type=event,
                evidence=evidence_for(synthetic_records["events"]),
            )
            for event in ["suspension", "resumption", "waiver", "default"]
        ],
        compliance_disclosures=[
            ComplianceDisclosure(
                status=status,
                description="Synthetic explicitly stated status",
                evidence=evidence_for(synthetic_records["status"]),
            )
            for status in ["deemed_compliant", "waived_default"]
        ],
    )
    assert {e.event_type for e in extraction.testing_events} == {
        "suspension",
        "resumption",
        "waiver",
        "default",
    }
    assert {d.status for d in extraction.compliance_disclosures} == {
        "deemed_compliant",
        "waived_default",
    }
    assert all(d.status != "compliant" for d in extraction.compliance_disclosures)


def test_adjustment_only_definition_and_unrelated_reported_value(synthetic_records, evidence_for):
    extraction = CovenantExtraction(
        financial_metric_definitions=[
            FinancialMetricDefinition(
                name="Consolidated EBITDA",
                definition=None,
                adjustments=[
                    "restructuring charges capped at $50 million for the twelve months "
                    "ended 2025-06-30"
                ],
                evidence=evidence_for(synthetic_records["adjustments"]),
            )
        ],
        reported_financial_values=[
            ReportedFinancialValue(
                metric_name="GAAP EBITDA",
                reported_value="$12.300 million",
                period_end="2025-06-30",
                measurement_period="three months",
                accounting_basis="GAAP",
                evidence=evidence_for(synthetic_records["gaap"]),
            )
        ],
        covenants=[
            CovenantTerm(
                covenant_name="Total Leverage",
                covenant_type="leverage",
                metric="Consolidated EBITDA",
                evidence=evidence_for(synthetic_records["base"]),
            )
        ],
        gaps=[
            "Full Consolidated EBITDA definition and explicit covenant definition "
            "link unavailable.",
            "Threshold not supplied in this expected-output fixture.",
        ],
    )
    report = validate_extraction(extraction, list(synthetic_records.values()))
    assert extraction.financial_metric_definitions[0].definition is None
    assert extraction.reported_financial_values[0].reported_value == "$12.300 million"
    assert extraction.covenants[0].metric_definition_name is None
    assert "missing_definition_link" in {i.code for i in report.issues}
    assert not any(v.reported_value == "$50 million" for v in extraction.reported_financial_values)


def test_reported_amount_keeps_units_period_and_precision(synthetic_records, evidence_for):
    extraction = CovenantExtraction(
        reported_financial_values=[
            ReportedFinancialValue(
                metric_name="Consolidated EBITDA",
                reported_value="$24.000 million",
                period_end="2025-06-30",
                measurement_period="twelve months",
                accounting_basis="contractual",
                evidence=evidence_for(synthetic_records["reported"]),
            )
        ]
    )
    assert validate_extraction(extraction, [synthetic_records["reported"]]).is_valid
    assert extraction.reported_financial_values[0].reported_value == "$24.000 million"
    assert CovenantExtraction().reported_financial_values == []
