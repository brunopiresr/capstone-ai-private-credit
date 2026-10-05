"""Compare stored V2 facts with public gold cases, offline and without changing facts.

The gold CSV also contains assessment labels which V2 does not represent. Those
are reported as unsupported, never treated as a successful extraction comparison.
See README.md in this directory for the mappings and coverage limits.
"""

import csv
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from credit_monitoring.domain import CovenantExtraction, ExtractionResult

ROOT = Path(__file__).resolve().parents[3]
GOLD_PATH = ROOT / "data/public_sec_gold_cases.csv"

# CSV classifications are more granular than the V2 enum. Name matching remains
# mandatory so secured, total, net, and rent-adjusted leverage cannot be confused.
TYPE_MAPPING = {
    "secured_leverage": "leverage",
    "total_leverage": "leverage",
    "net_leverage": "leverage",
    "rent_adjusted_leverage": "leverage",
    "minimum_revenue": "other",
}
NAME_MAPPING = {
    ("SRI", "compliance leverage ratio"): "net leverage ratio",
}
DIRECTION_MAPPING = {"maximum": "<=", "minimum": ">="}
STATUS_MAPPING = {
    "COMPLIANT": "compliant",
    "COMPLIANT_DISCLOSED": "compliant",
    "BREACH_DISCLOSED": "non_compliant",
    "BREACH_WAIVED": "waived_default",
}
EVENT_MAPPING = {"WAIVED": "waiver", "NOT_TESTED": "suspension"}
# These are benchmark annotations or assessment concepts, not V2 scalar facts.
UNSUPPORTED_FIELDS = {
    "amendment_applied": "V2 preserves amendment versions; it does not select legal precedence.",
    "waiver_status": "Free-text assessment; compare dated testing_events separately.",
    "early_warning_expected": "Temporal early-warning assessment is outside fact extraction.",
    "future_event_date": "Requires a separate temporal assessment of later evidence.",
    "future_event_type": "Free-text future-event assessment is outside fact extraction.",
}


@dataclass
class GoldCaseComparison:
    case_id: str
    checks: dict = field(default_factory=dict)
    missing_source_documents: list[str] = field(default_factory=list)
    unsupported: dict[str, str] = field(default_factory=dict)

    @property
    def mismatches(self):
        return {key: value for key, value in self.checks.items() if value["status"] == "mismatch"}

    @property
    def missing(self):
        return {key: value for key, value in self.checks.items() if value["status"] == "missing"}

    @property
    def is_complete(self):
        return not (
            self.mismatches or self.missing or self.missing_source_documents or self.unsupported
        )

    def compare(self, name, expected, observed, *, tolerance=Decimal("0")):
        values = sorted(set(observed), key=str)
        matches = all(
            abs(value - expected) <= tolerance
            if isinstance(value, Decimal) and isinstance(expected, Decimal)
            else value == expected
            for value in values
        )
        self.checks[name] = {
            "expected": expected,
            "observed": values,
            "status": "missing" if not values else "match" if matches else "mismatch",
        }


def _name(value, ticker):
    normalized = re.sub(r"\s+", " ", value.casefold()).strip()
    normalized = re.sub(r"^(maximum|minimum) ", "", normalized)
    return NAME_MAPPING.get((ticker, normalized), normalized)


def _applies(item, test_date):
    # Enumerated dates take priority: a redundant open range must not extend a
    # discrete schedule to all later quarters (present in the local FMC cache).
    if item.period_end_dates:
        return test_date in item.period_end_dates
    if item.from_period_end is not None:
        return item.from_period_end <= test_date and (
            item.through_period_end is None or test_date <= item.through_period_end
        )
    return False  # Undated facts cannot establish a period-specific gold threshold.


def _number(value, unit):
    """Strict numeric/unit projection; ambiguous strings stay visible as mismatches."""
    text = value.strip().replace(",", "")
    number = r"([+-]?\d+(?:\.\d+)?)"
    if unit == "x":
        ratio = re.fullmatch(number + r"\s*(?:to|:)\s*(\d+(?:\.\d+)?)", text, re.I)
        if ratio and Decimal(ratio[2]) != 0:
            return Decimal(ratio[1]) / Decimal(ratio[2])
        match = re.fullmatch(number + r"\s*(?:x|times)?", text, re.I)
        if match:
            return Decimal(match[1])
    elif unit == "USD_m":
        match = re.fullmatch(r"(?:USD\s*|\$)?" + number + r"\s*(million|m|billion|bn)?", text, re.I)
        if match:
            amount = Decimal(match[1])
            scale = (match[2] or "").casefold()
            return (
                amount * 1000
                if scale in {"billion", "bn"}
                else (amount if scale in {"million", "m"} else amount / 1_000_000)
            )
    return value


def validate_gold_case(
    gold: dict[str, str], extractions: dict[str, CovenantExtraction]
) -> GoldCaseComparison:
    """Compare one CSV row to unmodified, independently produced V2 objects.

    Keys are source document IDs. Only gold-listed sources are considered. All
    applicable versions are checked; conflicts fail instead of selecting the
    version that happens to agree with the gold threshold. Missing data is
    distinct from a mismatch. Benchmark answers never supply observed values.
    """
    report = GoldCaseComparison(gold["case_id"])
    source_ids = set(gold["source_document_ids"].split(";"))
    report.missing_source_documents = sorted(source_ids - extractions.keys())
    report.unsupported = {
        key: reason for key, reason in UNSUPPORTED_FIELDS.items() if gold.get(key)
    }
    supplied = [extractions[key] for key in sorted(source_ids & extractions.keys())]
    ticker = gold["ticker"]
    test_date = date.fromisoformat(gold["test_date"])
    name = _name(gold["covenant_name"], ticker)
    terms = [
        term
        for extraction in supplied
        for term in extraction.covenants
        if _name(term.covenant_name, ticker) == name
    ]
    report.compare("ticker", ticker, [e.ticker for e in supplied if e.ticker])
    # In this public CSV, borrower is the catalog registrant, not necessarily
    # the borrowing subsidiary. V2 issuer is the corresponding comparison field.
    report.compare(
        "borrower", gold["borrower"].casefold(), [e.issuer.casefold() for e in supplied if e.issuer]
    )
    used_evidence = [term.evidence for term in terms]
    if gold["covenant_type"] != "borrower_event":
        report.compare("covenant_name", name, [_name(t.covenant_name, ticker) for t in terms])
        if gold["covenant_type"] == "early_warning":
            report.unsupported["covenant_type"] = "Early warning is an assessment, not a V2 type."
        else:
            report.compare(
                "covenant_type",
                TYPE_MAPPING.get(gold["covenant_type"], gold["covenant_type"]),
                [t.covenant_type for t in terms],
            )

    schedules = [
        entry for term in terms for entry in term.threshold_schedule if _applies(entry, test_date)
    ]
    if gold["threshold_value"]:
        report.compare("test_date", test_date, [test_date for _ in schedules])
        report.compare(
            "threshold_value",
            Decimal(gold["threshold_value"]),
            [_number(s.threshold, gold["unit"]) for s in schedules],
        )
        used_evidence.extend(s.evidence for s in schedules)
    active_terms = [t for t in terms if any(_applies(s, test_date) for s in t.threshold_schedule)]
    operator_terms = active_terms if gold["threshold_value"] else terms
    if gold["operator"] in {"<", "<=", ">", ">=", "="}:
        report.compare(
            "operator",
            gold["operator"],
            [
                t.operator or DIRECTION_MAPPING.get(t.threshold_direction)
                for t in operator_terms
                if t.operator or t.threshold_direction in DIRECTION_MAPPING
            ],
        )
    elif gold["operator"] in EVENT_MAPPING:
        events = [
            event
            for e in supplied
            for event in e.testing_events
            if _name(event.covenant_name, ticker) == name and _applies(event, test_date)
        ]
        report.compare(
            "operator",
            EVENT_MAPPING[gold["operator"]],
            [event.event_type for event in events if event.event_type in {"waiver", "suspension"}],
        )
        used_evidence.extend(event.evidence for event in events)

    metric_names = {name} | {_name(t.metric, ticker) for t in terms if t.metric}
    disclosures = [
        d
        for e in supplied
        for d in e.compliance_disclosures
        if d.assessment_date == test_date
        and (
            d.covenant_name is None
            if gold["covenant_type"] == "borrower_event"
            else d.covenant_name and _name(d.covenant_name, ticker) == name
        )
    ]
    values = [
        v
        for e in supplied
        for v in e.reported_financial_values
        if v.period_end == test_date and _name(v.metric_name, ticker) in metric_names
    ]
    actuals = [_number(v.reported_value, gold["unit"]) for v in values]
    actuals.extend(
        _number(d.reported_result, gold["unit"]) for d in disclosures if d.reported_result
    )
    used_evidence.extend(v.evidence for v in values)
    used_evidence.extend(d.evidence for d in disclosures)
    if gold["actual_value"]:
        report.compare(
            "actual_value", Decimal(gold["actual_value"]), actuals, tolerance=Decimal("0.005")
        )
    if gold["headroom"]:
        # Calculate from observed facts only, never CSV threshold/actual values.
        observed_operators = report.checks.get("operator", {}).get("observed", [])
        headrooms = []
        for schedule in schedules:
            threshold = _number(schedule.threshold, gold["unit"])
            for actual in actuals:
                if isinstance(threshold, Decimal) and isinstance(actual, Decimal):
                    for operator in observed_operators:
                        if operator in {"<", "<=", ">", ">="}:
                            headrooms.append(
                                threshold - actual
                                if operator in {"<", "<="}
                                else actual - threshold
                            )
        report.compare("headroom", Decimal(gold["headroom"]), headrooms, tolerance=Decimal("0.005"))
    status = gold["gold_status"]
    if status in STATUS_MAPPING:
        report.compare("gold_status", STATUS_MAPPING[status], [d.status for d in disclosures])
    elif status in EVENT_MAPPING:
        report.compare(
            "gold_status",
            EVENT_MAPPING[status],
            report.checks.get("operator", {}).get("observed", []),
        )
    else:
        report.unsupported["gold_status"] = f"{status} requires an assessment beyond V2 facts."
    report.compare(
        "source_document_ids",
        True,
        [evidence.document_id in source_ids for evidence in used_evidence],
    )
    return report


def load_cached_extractions(database_path):
    """Read the newest document state without creating or updating SQLite files."""
    path = Path(database_path).resolve()
    if not path.exists():
        return {}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT document_id, status, result_json FROM document_extractions "
            "ORDER BY updated_at DESC, cache_key DESC"
        ).fetchall()
    results, seen = {}, set()
    for document_id, status, payload in rows:
        if document_id in seen:
            continue
        seen.add(document_id)
        if status == "complete" and payload:
            results[document_id] = ExtractionResult.model_validate_json(payload).extraction
    return results


with GOLD_PATH.open(newline="", encoding="utf-8") as file:
    GOLD_CASES = list(csv.DictReader(file))


@pytest.fixture(scope="module")
def cached_extractions():
    return load_cached_extractions(
        os.environ.get("SEC_GOLD_DATABASE", ROOT / "data/processed/covenants.sqlite3")
    )


@pytest.mark.parametrize("gold", GOLD_CASES, ids=lambda row: row["case_id"])
def test_cached_covenants_against_public_sec_gold_cases(gold, cached_extractions, record_property):
    report = validate_gold_case(gold, cached_extractions)
    record_property("gold_comparison", json.dumps(report.__dict__, default=str))
    if not set(gold["source_document_ids"].split(";")) & cached_extractions.keys():
        pytest.skip("No completed local extraction for this case's source documents.")
    assert not report.mismatches, json.dumps(report.__dict__, indent=2, default=str)
    # A partial cache may check amendment thresholds without quarterly results.
    # Require the core term facts, and all supported facts once sources are complete.
    required = {"ticker", "borrower", "covenant_name", "covenant_type", "source_document_ids"}
    required |= {"test_date", "threshold_value", "operator"} & report.checks.keys()
    assert not required & report.missing.keys(), json.dumps(report.__dict__, indent=2, default=str)
    if not report.missing_source_documents:
        assert not report.missing, json.dumps(report.__dict__, indent=2, default=str)


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
