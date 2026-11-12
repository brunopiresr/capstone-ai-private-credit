"""Copied tool and saved-assessment context; interpretation belongs to the agent."""

import hashlib
import json
from dataclasses import dataclass, field

from credit_monitoring.agents.presentation import calculation_details
from credit_monitoring.domain.agent import EvidenceEntry
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult
from credit_monitoring.domain.documents import RetrievedRecord
from credit_monitoring.domain.processing import DocumentExtraction, DocumentSummary
from credit_monitoring.domain.tool_results import FinancialReview, ToolOutcome


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _document_prompt_data(data: dict) -> dict:
    """Keep source facts concise; complete quotations remain in tool history and storage."""
    if data.get("status") != "complete" or not isinstance(data.get("result"), dict):
        return data

    def compact(value):
        if isinstance(value, dict):
            if {"evidence_quote", "document_id", "citation"} <= value.keys():
                return {key: value[key] for key in ("document_id", "citation")}
            return {key: compact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    projected = compact(data)
    for covenant in projected["result"]["extraction"]["covenants"]:
        rows = []
        citations = []
        named_periods = 0
        for entry in covenant["threshold_schedule"]:
            citation = entry.pop("evidence")
            if citation not in citations:
                citations.append(citation)
            entry["citation_index"] = citations.index(citation)
            dates = entry["period_end_dates"]
            named_periods += len(dates)
            rows.extend({**entry, "period_end_dates": [day]} for day in dates)
            if not dates:
                rows.append(entry)
        covenant["threshold_schedule"] = rows
        covenant["schedule_citations"] = citations
        covenant["explicitly_named_period_count"] = named_periods
    extraction = projected["result"]["extraction"]
    projected["available_source_tables"] = [
        section
        for section, available in (
            ("covenant_schedules", any(c["threshold_schedule"] for c in extraction["covenants"])),
            ("reported_values", bool(extraction["reported_financial_values"])),
        )
        if available
    ]
    return projected


@dataclass
class EvidenceRegistry:
    _entries: dict[str, EvidenceEntry] = field(default_factory=dict)

    @property
    def entries(self) -> tuple[EvidenceEntry, ...]:
        return tuple(item.model_copy(deep=True) for item in self._entries.values())

    def retain(self, entries: list[EvidenceEntry]) -> None:
        self._entries.update({entry.evidence_id: entry.model_copy(deep=True) for entry in entries})

    def _add(
        self,
        evidence_id,
        kind,
        data,
        citation,
        borrower_id=None,
        ticker=None,
        period_end=None,
        information_cutoff=None,
    ) -> None:
        self._entries[evidence_id] = EvidenceEntry(
            evidence_id=evidence_id,
            kind=kind,
            payload_json=canonical(data),
            citation=citation,
            borrower_id=borrower_id,
            ticker=ticker,
            period_end=period_end,
            information_cutoff=information_cutoff,
        )

    def _financial(self, financial: FinancialPeriod, cutoff: str) -> None:
        if financial.source_file is not None and financial.source_row is not None:
            data = financial.model_dump(mode="json", exclude={"loaded_at"})
            identifier = hashlib.sha256(canonical([data, cutoff]).encode()).hexdigest()[:20]
            self._add(
                f"csv:{identifier}",
                "csv",
                data,
                f"{financial.source_file}, row {financial.source_row}",
                financial.borrower_id,
                period_end=str(financial.period_end),
                information_cutoff=cutoff,
            )

    def record(self, outcome: ToolOutcome, *, borrower_id: str | None, ticker: str | None) -> None:
        if isinstance(outcome, FinancialReview):
            for financial in ([outcome.current] if outcome.current else []) + outcome.history:
                self._financial(financial, str(outcome.information_cutoff))
        elif isinstance(outcome, RiskAssessment):
            run, period, cutoff = (
                outcome.assessment_run_id,
                str(outcome.period_end),
                str(outcome.information_cutoff),
            )
            data = outcome.model_dump(mode="json", exclude={"narrative", "results", "history"})
            self._add(
                f"assessment:{run}",
                "assessment",
                data,
                f"assessment {run}",
                outcome.borrower_id,
                period_end=period,
                information_cutoff=cutoff,
            )
            for result in [*outcome.results, *outcome.history]:
                data = result.model_dump(mode="json")
                data["presentation"] = calculation_details(data)
                self._add(
                    f"calculation:{run}:{result.result_id}",
                    "calculation",
                    data,
                    f"assessment {run}, result {result.result_id}",
                    result.borrower_id,
                    period_end=str(result.period_end),
                    information_cutoff=cutoff,
                )
                if raw := result.financial_inputs.get("financial_period"):
                    self._financial(FinancialPeriod.model_validate(raw), cutoff)
            if prediction := outcome.prediction:
                self._add(
                    f"prediction:{prediction.prediction_id}",
                    "prediction",
                    prediction.model_dump(mode="json"),
                    f"assessment {run}, prediction {prediction.prediction_id}",
                    prediction.borrower_id,
                    period_end=str(prediction.period_end),
                    information_cutoff=cutoff,
                )
        elif isinstance(outcome, list):
            for record in outcome:
                if isinstance(record, (RetrievedRecord, DocumentSummary)):
                    self._document(record, ticker)
        elif isinstance(outcome, DocumentExtraction):
            self._document(outcome, ticker)

    def _document(self, record: RetrievedRecord | DocumentSummary, ticker: str | None) -> None:
        data = record.model_dump(mode="json")
        identifier = hashlib.sha256(canonical(data).encode()).hexdigest()[:20]
        # Re-reading a known extraction makes its status the latest observed state.
        if isinstance(record, DocumentExtraction):
            self._entries.pop(f"filing:{identifier}", None)
        self._add(
            f"filing:{identifier}",
            "filing",
            data,
            f"{record.document_id}: {record.citation}",
            ticker=record.ticker or ticker,
            period_end=getattr(record, "period_end", None),
        )

    def prompt(self) -> str:
        return canonical(
            [
                {
                    **entry.model_dump(exclude={"payload_json"}),
                    "data": _document_prompt_data(entry.data)
                    if entry.kind == "filing"
                    else entry.data,
                }
                for entry in self.entries
            ]
        )

    def record_review(
        self, review: CreditReviewResult, *, borrower_id: str, assessment_run_id: str
    ) -> None:
        data = {
            "review_id": review.review_id,
            "basis": "Saved agent opinions, not source facts",
            "recommendation": review.recommendation.model_dump(mode="json"),
            "bullish": review.bullish.model_dump(mode="json"),
            "bearish": review.bearish.model_dump(mode="json"),
        }
        self._add(
            f"review:{review.review_id}",
            "review",
            data,
            f"saved review {review.review_id} (agent opinions)",
            borrower_id,
            period_end=str(review.snapshot.period_end),
            information_cutoff=str(
                review.snapshot.review_information_cutoff or review.snapshot.information_cutoff
            ),
        )
