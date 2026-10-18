"""Read-only comparison of independently observed SEC facts with benchmark expectations."""

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from credit_monitoring.domain import CovenantExtraction, ExtractionResult

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
