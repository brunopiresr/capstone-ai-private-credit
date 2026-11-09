"""Application-owned scope, analyst dates and per-turn dispatch prerequisites.

Only the current analyst question, dates retained from successful analyst turns,
or explicit UI selections enter resolution. Assistant/tool messages never do.
Unrecognized date phrasing is clarified rather than guessed.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from credit_monitoring.agents.tools.common import InvalidToolArguments

type Intent = Literal[
    "assessment", "forecast", "evidence", "follow_up", "clarification", "scope", "unrelated"
]


@dataclass(frozen=True)
class AnalystDate:
    value: date
    original_text: str
    origin: Literal["analyst", "ui_selection"] = "analyst"


@dataclass(frozen=True)
class RequestContext:
    intent: Intent
    borrower_id: str | None
    ticker: str | None
    reporting: AnalystDate | None = None
    cutoff: AnalystDate | None = None
    response: str | None = None
    requested_intent: Intent | None = None

    @property
    def dates(self) -> dict[str, str]:
        return (
            {
                "period_end": self.reporting.value.isoformat(),
                "information_cutoff": self.cutoff.value.isoformat(),
            }
            if (self.reporting and self.cutoff)
            else {}
        )


def resolve_request(
    question: str,
    *,
    borrower_id: str | None,
    ticker: str | None,
    retained: dict[str, AnalystDate] | None = None,
    selected_dates: tuple[date, date] | None = None,
    has_evidence: bool = False,
    retained_intent: Intent | None = None,
) -> RequestContext:
    text = question.casefold()
    dates = dict(retained or {})
    scope = borrower_id or ticker or "the configured issuer"
    response = None
    if selected_dates:
        dates = {
            key: AnalystDate(value, value.isoformat(), "ui_selection")
            for key, value in zip(("reporting", "cutoff"), selected_dates, strict=True)
        }
    # Scope is a routing decision, not a new borrower-to-issuer mapping.
    mentioned = set(re.findall(r"\bSYN\d+\b", question, flags=re.I))
    switching = re.search(
        r"\b(?:switch|change)\s+(?:(?:this|the|scoped)\s+)*"
        r"(?:issuer|borrower|scope|conversation|to)\b",
        text,
    )
    if (borrower_id and any(b.casefold() != borrower_id.casefold() for b in mentioned)) or (
        switching and (ticker or borrower_id)
    ):
        return RequestContext(
            "scope",
            borrower_id,
            ticker,
            dates.get("reporting"),
            dates.get("cutoff"),
            response=(
                f"This conversation is scoped to {scope}. Start a new scoped conversation "
                "to review another borrower or issuer."
            ),
        )
    if re.search(
        r"\b(weather|poem|recipe|cake|headache|prescription|cryptocurrency|"
        r"romantic|platform game|javascript game)\b",
        text,
    ):
        return RequestContext(
            "unrelated",
            borrower_id,
            ticker,
            dates.get("reporting"),
            dates.get("cutoff"),
            response=(
                f"I can help with credit monitoring and covenant assessments for {scope}. "
                "Ask a credit question within this scope."
            ),
        )

    evidence_only = re.search(
        r"\b(find|search|filing|document|disclosure|passage|catalog|evidence)\b", text
    )
    forecast = re.search(
        r"\b(forecast|predict|prediction|probability|next.quarter|future risk)\b", text
    )
    fresh = re.search(
        r"\b(assess|assessment|reassess|recalculate|refresh|rerun|compliance|"
        r"compliant|breach|headroom|covenant|okay)\b",
        text,
    )
    intent: Intent = (
        "evidence"
        if evidence_only and not forecast and not fresh
        else "forecast"
        if forecast
        else "assessment"
        if borrower_id and fresh
        else "follow_up"
        if has_evidence
        else "evidence"
        if not borrower_id
        else "clarification"
    )
    # A date-only reply completes an assessment request without relying on assistant text.
    if borrower_id and re.search(r"reporting|period|cutoff|as.of", text):
        intent = (
            "forecast"
            if forecast or (not fresh and retained_intent == "forecast")
            else "assessment"
        )
    both = re.search(
        r"reporting (?:date|period) and information cutoff (?:are )?both "
        r"(\d{4}-\d{2}-\d{2})",
        text,
    )
    if both:
        try:
            value = date.fromisoformat(both.group(1))
            dates.update({k: AnalystDate(value, both.group(0)) for k in ("reporting", "cutoff")})
        except ValueError:
            response = "Please provide valid reporting and cutoff dates in YYYY-MM-DD format."

    for key, label in (
        (
            "reporting",
            r"(?:reporting(?:\s+(?:date|period|period\s+end))?|"
            r"period(?:\s+end)?|as.of)",
        ),
        ("cutoff", r"(?:information\s+cutoff|cutoff)"),
    ):
        matches = list(
            re.finditer(
                label + r"\s*(?:date)?\s*(?:is|to)?\s*[:=]?\s*"
                r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|latest)",
                text,
            )
        )
        if matches:
            raw_values = {m.group(1) for m in matches}
            if len(raw_values) > 1:
                response = f"Please clarify the {key} date; the request supplies conflicting dates."
                dates.pop(key, None)
                break
            raw = matches[-1].group(1)
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                    raise ValueError("Ambiguous date")
                value = date.fromisoformat(raw)
            except ValueError:
                response = f"Please supply an unambiguous valid {key} date in YYYY-MM-DD format."
                dates.pop(key, None)
                break
            dates[key] = AnalystDate(value, matches[-1].group(0))
    if intent in {"evidence", "follow_up"}:
        return RequestContext(
            intent, borrower_id, ticker, dates.get("reporting"), dates.get("cutoff")
        )
    if not response and not all(key in dates for key in ("reporting", "cutoff")):
        missing = [
            "reporting date" if k == "reporting" else "information cutoff"
            for k in ("reporting", "cutoff")
            if k not in dates
        ]
        response = "Please provide the " + " and ".join(missing) + " in YYYY-MM-DD format."
    if not response and dates["cutoff"].value < dates["reporting"].value:
        response = "Please provide an information cutoff on or after the reporting date."
    if intent == "clarification" and not response:
        response = (
            "Please clarify whether you want a covenant assessment, forecast or evidence lookup."
        )
    return RequestContext(
        "clarification" if response else intent,
        borrower_id,
        ticker,
        dates.get("reporting"),
        dates.get("cutoff"),
        response,
        intent,
    )


@dataclass
class DispatchPolicy:
    context: RequestContext
    stage: Literal["ready", "financials", "assessed"] = "ready"
    terminal_response: str | None = None
    attempts: list[str] = field(default_factory=list)

    def admit(self, tool: str, period: date, cutoff: date) -> None:
        self.attempts.append(tool)
        if self.terminal_response or self.context.intent not in {"assessment", "forecast"}:
            raise InvalidToolArguments("This request does not admit financial assessment calls.")
        if {"period_end": period.isoformat(), "information_cutoff": cutoff.isoformat()} != (
            self.context.dates
        ):
            raise InvalidToolArguments(
                "Use the validated analyst dates: " + str(self.context.dates)
            )
        if self.stage == "assessed":
            raise InvalidToolArguments("An assessment already succeeded; answer from that result.")
        expected = "predict_risk" if self.context.intent == "forecast" else "assess_covenants"
        if tool != "get_financials" and (tool != expected or self.stage != "financials"):
            raise InvalidToolArguments("Required sequence: get_financials -> " + expected)

    def succeeded(self, tool: str) -> None:
        self.stage = "financials" if tool == "get_financials" else "assessed"

    def validate_final(self) -> None:
        if self.context.intent in {"assessment", "forecast"} and self.stage != "assessed":
            raise ValueError("Execute the required financial read and assessment before answering.")
