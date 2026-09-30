"""Read-only access to the repository's synthetic covenant monitoring examples."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_DATA_ROOT = Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True)
class DemoAssessment:
    """Pre-labeled benchmark example presented as a mocked assessment."""

    borrower_id: str
    borrower_name: str
    scenario: str
    period_end: str
    covenant_id: str
    covenant_name: str
    formula: str
    operator: str
    threshold: float
    unit: str
    metric: float | None
    headroom: float | None
    status: str
    early_warning: bool
    rationale: str
    financial_facts: dict[str, str]
    history: tuple[tuple[str, float], ...]
    case_id: str
    evidence_issue: str


@dataclass(frozen=True)
class PortfolioItem:
    """One borrower's latest or selected synthetic portfolio case."""

    assessment: DemoAssessment
    industry: str
    trend: str
    action: str


def _read_csv(filename: str) -> list[dict[str, str]]:
    with (_DATA_ROOT / filename).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def get_borrowers() -> list[dict[str, str]]:
    """Return synthetic borrowers with at least one expected assessment."""
    names = {row["borrower_id"]: row for row in _read_csv("synthetic_borrowers.csv")}
    cases = _read_csv("synthetic_gold_labels.csv")
    borrower_ids = {row["borrower_id"] for row in cases}
    return sorted((names[key] for key in borrower_ids), key=lambda row: row["borrower_name"])


def get_periods(borrower_id: str) -> list[str]:
    """Return available benchmark reporting dates for one borrower."""
    return sorted(
        {
            row["period_end"]
            for row in _read_csv("synthetic_gold_labels.csv")
            if row["borrower_id"] == borrower_id
        }
    )


def get_portfolio_periods() -> list[str]:
    """Return reporting dates available anywhere in the synthetic benchmark."""
    return sorted({row["period_end"] for row in _read_csv("synthetic_gold_labels.csv")})


def build_portfolio_snapshot(period_end: str | None = None) -> list[PortfolioItem]:
    """Build a portfolio list from each borrower's latest case or a chosen period."""
    borrower_rows = {row["borrower_id"]: row for row in get_borrowers()}
    cases = _read_csv("synthetic_gold_labels.csv")
    portfolio: list[PortfolioItem] = []

    for borrower_id, borrower in borrower_rows.items():
        available_periods = sorted(
            row["period_end"]
            for row in cases
            if row["borrower_id"] == borrower_id
            and (period_end is None or row["period_end"] == period_end)
        )
        if not available_periods:
            continue
        selected_period = available_periods[-1]
        assessment = build_demo_assessment(borrower_id, selected_period)
        history = assessment.history
        if len(history) < 2:
            trend = "New"
        else:
            delta = history[-1][1] - history[-2][1]
            worsening = delta > 0 if assessment.operator == "<=" else delta < 0
            trend = "Worsening" if worsening else "Improving" if delta else "Flat"

        action = {
            "BREACH": "Review now",
            "WATCH": "Review trend",
            "INCOMPLETE": "Resolve data",
            "COMPLIANT": "Routine",
        }[assessment.status]
        portfolio.append(
            PortfolioItem(
                assessment=assessment,
                industry=borrower["industry"],
                trend=trend,
                action=action,
            )
        )

    priority = {"BREACH": 0, "WATCH": 1, "INCOMPLETE": 2, "COMPLIANT": 3}
    return sorted(
        portfolio,
        key=lambda item: (
            priority[item.assessment.status],
            item.assessment.borrower_name,
        ),
    )


def build_demo_assessment(borrower_id: str, period_end: str) -> DemoAssessment:
    """Assemble one fixed benchmark case without calling an agent or external service."""
    borrower = next(
        row for row in _read_csv("synthetic_borrowers.csv") if row["borrower_id"] == borrower_id
    )
    case_rows = _read_csv("synthetic_gold_labels.csv")
    case = next(
        row
        for row in case_rows
        if row["borrower_id"] == borrower_id and row["period_end"] == period_end
    )
    covenant = next(
        row
        for row in _read_csv("synthetic_covenant_terms.csv")
        if row["borrower_id"] == borrower_id
        and row["covenant_id"] == case["covenant_id"]
        and row["effective_start"] <= period_end
        and (not row["effective_end"] or period_end <= row["effective_end"])
    )
    financial_row = next(
        row
        for row in _read_csv("synthetic_quarterly_financials.csv")
        if row["borrower_id"] == borrower_id and row["period_end"] == period_end
    )

    status = {
        "COMPLIANT": "COMPLIANT",
        "COMPLIANT_EARLY_WARNING": "WATCH",
        "BREACH": "BREACH",
        "DATA_CONFLICT_ABSTAIN": "INCOMPLETE",
        "WAIVED": "INCOMPLETE",
        "NOT_TESTED": "INCOMPLETE",
    }.get(case["expected_status"], "INCOMPLETE")
    metric = float(case["expected_metric"]) if case["expected_metric"] else None
    headroom = float(case["expected_headroom"]) if case["expected_headroom"] else None
    financial_facts = {
        key: value
        for key, value in financial_row.items()
        if value and key not in {"borrower_id", "period_end", "notes"}
    }
    history = tuple(
        (row["period_end"], float(row["expected_metric"]))
        for row in case_rows
        if row["borrower_id"] == borrower_id
        and row["covenant_id"] == case["covenant_id"]
        and row["period_end"] <= period_end
        and row["expected_metric"]
    )

    return DemoAssessment(
        borrower_id=borrower_id,
        borrower_name=borrower["borrower_name"],
        scenario=borrower["scenario"],
        period_end=period_end,
        covenant_id=case["covenant_id"],
        covenant_name=covenant["covenant_name"],
        formula=covenant["metric_formula"],
        operator=covenant["operator"],
        threshold=float(covenant["threshold"]),
        unit=covenant["unit"],
        metric=metric,
        headroom=headroom,
        status=status,
        early_warning=case["early_warning_expected"].lower() == "true",
        rationale=case["rationale"],
        financial_facts=financial_facts,
        history=history,
        case_id=case["case_id"],
        evidence_issue=case["expected_evidence_issue"],
    )
