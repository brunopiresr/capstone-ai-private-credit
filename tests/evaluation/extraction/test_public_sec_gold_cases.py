"""Portable comparator contracts using independent observations, without a local cache."""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.evaluation.sec_gold import (
    _applies,
    _number,
    load_cached_extractions,
    validate_gold_case,
)

ROOT = Path(__file__).resolve().parents[3]
GOLD_PATH = ROOT / "data/public_sec_gold_cases.csv"
with GOLD_PATH.open(newline="", encoding="utf-8") as file:
    GOLD_CASES = list(csv.DictReader(file))


@pytest.fixture
def fmc_facts():
    """Independent controlled V2 objects, not observations generated from the CSV."""
    amendment = "DOC_FMC_AMD3_2025"
    quarterly = "DOC_FMC_Q1_2025"

    def evidence(document_id):
        return {
            "document_id": document_id,
            "citation": "Controlled test fixture",
            "evidence_quote": "Controlled comparison facts; not a live extraction.",
        }

    terms = CovenantExtraction.model_validate(
        {
            "issuer": "FMC Corporation",
            "ticker": "FMC",
            "covenants": [
                {
                    "covenant_name": "Maximum Leverage Ratio",
                    "covenant_type": "leverage",
                    "metric": "Leverage Ratio",
                    "operator": None,
                    "threshold_direction": "maximum",
                    "evidence": evidence(amendment),
                    "threshold_schedule": [
                        {
                            "threshold": "5.25 to 1.00",
                            "period_end_dates": ["2025-03-31", "2025-09-30"],
                            "from_period_end": "2025-03-31",
                            "evidence": evidence(amendment),
                        }
                    ],
                }
            ],
        }
    )
    results = CovenantExtraction.model_validate(
        {
            "issuer": "FMC Corporation",
            "ticker": "FMC",
            "reported_financial_values": [
                {
                    "metric_name": "Leverage Ratio",
                    "reported_value": "4.77x",
                    "period_end": "2025-03-31",
                    "evidence": evidence(quarterly),
                }
            ],
            "compliance_disclosures": [
                {
                    "covenant_name": "Maximum Leverage Ratio",
                    "status": "compliant",
                    "assessment_date": "2025-03-31",
                    "description": "Controlled disclosure.",
                    "evidence": evidence(quarterly),
                }
            ],
        }
    )
    return {amendment: terms, quarterly: results}


def _gold(case_id):
    return next(row for row in GOLD_CASES if row["case_id"] == case_id)


def test_full_fmc_comparison_and_input_objects_are_unchanged(fmc_facts):
    before = {key: value.model_dump_json() for key, value in fmc_facts.items()}
    report = validate_gold_case(_gold("PUB_FMC_2025Q1_LEV"), fmc_facts)
    assert not report.mismatches and not report.missing
    assert report.checks["headroom"]["observed"] == [Decimal("0.48")]
    assert report.checks["operator"]["observed"] == ["<="]
    assert "amendment_applied" in report.unsupported
    assert not report.is_complete  # Matching extraction facts do not validate legal assessments.
    assert before == {key: value.model_dump_json() for key, value in fmc_facts.items()}


@pytest.mark.parametrize(
    "field_name",
    [
        "ticker",
        "borrower",
        "covenant_type",
        "threshold_value",
        "operator",
        "actual_value",
        "gold_status",
        "source_document_ids",
    ],
)
def test_incorrect_observed_facts_fail_comparison(field_name, fmc_facts):
    terms = fmc_facts["DOC_FMC_AMD3_2025"]
    results = fmc_facts["DOC_FMC_Q1_2025"]
    term = terms.covenants[0]
    if field_name == "ticker":
        terms.ticker = "OTHER"
    elif field_name == "borrower":
        terms.issuer = "Other Issuer"
    elif field_name == "covenant_type":
        term.covenant_type = "other"
    elif field_name == "threshold_value":
        term.threshold_schedule[0].threshold = "6.00 to 1.00"
    elif field_name == "operator":
        term.operator = ">="
    elif field_name == "actual_value":
        results.reported_financial_values[0].reported_value = "4.94x"
    elif field_name == "gold_status":
        results.compliance_disclosures[0].status = "non_compliant"
    else:
        term.threshold_schedule[0].evidence.document_id = "UNLISTED_DOCUMENT"
    report = validate_gold_case(_gold("PUB_FMC_2025Q1_LEV"), fmc_facts)
    assert field_name in report.mismatches


def test_partial_cache_reports_missing_actuals_instead_of_using_gold_values(fmc_facts):
    del fmc_facts["DOC_FMC_Q1_2025"]
    report = validate_gold_case(_gold("PUB_FMC_2025Q1_LEV"), fmc_facts)
    assert not report.mismatches
    assert {"actual_value", "headroom", "gold_status"} <= report.missing.keys()
    assert report.missing_source_documents == ["DOC_FMC_Q1_2025"]
    assert not report.is_complete


def test_wrong_period_does_not_match_and_discrete_schedule_does_not_extend(fmc_facts):
    fmc_facts["DOC_FMC_Q1_2025"].reported_financial_values[0].period_end = date(2025, 6, 30)
    schedule = fmc_facts["DOC_FMC_AMD3_2025"].covenants[0].threshold_schedule[0]
    schedule.period_end_dates = [date(2025, 6, 30)]
    report = validate_gold_case(_gold("PUB_FMC_2025Q1_LEV"), fmc_facts)
    assert {"test_date", "threshold_value", "operator", "actual_value", "headroom"} <= (
        report.missing.keys()
    )
    assert not _applies(schedule, date(2025, 9, 30))
    schedule.period_end_dates = []
    schedule.through_period_end = date(2025, 9, 30)
    assert _applies(schedule, date(2025, 9, 30))
    assert not _applies(schedule, date(2025, 12, 31))


def test_conflicting_versions_are_not_resolved_by_the_gold_answer(fmc_facts):
    term = fmc_facts["DOC_FMC_AMD3_2025"].covenants[0]
    stale = term.model_copy(deep=True)
    stale.threshold_schedule[0].threshold = "4.75 to 1.00"
    fmc_facts["DOC_FMC_AMD3_2025"].covenants.append(stale)
    report = validate_gold_case(_gold("PUB_FMC_2025Q1_LEV"), fmc_facts)
    assert report.mismatches["threshold_value"]["observed"] == [Decimal("4.75"), Decimal("5.25")]


def test_same_type_different_covenant_cannot_supply_a_missing_threshold(fmc_facts):
    fmc_facts["DOC_FMC_AMD3_2025"].covenants[0].covenant_name = "Maximum Secured Leverage Ratio"
    report = validate_gold_case(_gold("PUB_FMC_2025Q1_LEV"), fmc_facts)
    assert {"covenant_name", "covenant_type", "threshold_value"} <= report.missing.keys()


@pytest.mark.parametrize(
    "text,unit,expected",
    [
        ("5.25 to 1.00", "x", "5.25"),
        ("10.5:2.0", "x", "5.25"),
        ("3.00x", "x", "3"),
        ("$9,500,000", "USD_m", "9.5"),
        ("USD 35 million", "USD_m", "35"),
        ("$0.073 billion", "USD_m", "73"),
    ],
)
def test_numeric_unit_mapping(text, unit, expected):
    assert _number(text, unit) == Decimal(expected)


@pytest.mark.parametrize(
    "text,unit",
    [
        ("between 5 and 6", "x"),
        ("5 to 0", "x"),
        ("$5 million", "x"),
        ("EUR 9 million", "USD_m"),
    ],
)
def test_ambiguous_or_incompatible_units_remain_mismatches(text, unit):
    assert _number(text, unit) == text


@pytest.mark.parametrize(
    "case_id,event_type",
    [
        ("PUB_SRI_2024Q4_ICR_WAIVER", "waiver"),
        ("PUB_AVD_2025Q2_LEV_SUSPENDED", "suspension"),
    ],
)
def test_waiver_and_suspension_are_events_not_comparison_operators(case_id, event_type):
    gold = _gold(case_id)
    document_id = gold["source_document_ids"].split(";")[0]
    extraction = CovenantExtraction.model_validate(
        {
            "issuer": gold["borrower"],
            "ticker": gold["ticker"],
            "testing_events": [
                {
                    "covenant_name": gold["covenant_name"],
                    "event_type": event_type,
                    "period_end_dates": [gold["test_date"]],
                    "evidence": {
                        "document_id": document_id,
                        "citation": "Controlled test fixture",
                        "evidence_quote": "Controlled legal event.",
                    },
                }
            ],
        }
    )
    report = validate_gold_case(gold, {document_id: extraction})
    assert report.checks["operator"]["status"] == "match"
    assert report.checks["gold_status"]["status"] == "match"
    assert "threshold_value" not in report.checks
    extraction.testing_events[0].period_end_dates = [date(2027, 3, 31)]
    assert "operator" in validate_gold_case(gold, {document_id: extraction}).missing


def test_missing_cache_is_read_only_and_does_not_create_a_database(tmp_path):
    path = tmp_path / "absent.sqlite3"
    assert load_cached_extractions(path) == {}
    assert not path.exists()
