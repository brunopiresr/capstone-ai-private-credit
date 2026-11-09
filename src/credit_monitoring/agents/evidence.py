"""Executed and retained evidence with scope/period partitions and immutable views."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date

from credit_monitoring.agents.presentation import calculation_details
from credit_monitoring.domain.agent import EvidenceEntry
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult
from credit_monitoring.domain.documents import RetrievedRecord
from credit_monitoring.domain.processing import DocumentExtraction
from credit_monitoring.domain.tool_results import FinancialReview, ToolOutcome


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


@dataclass
class EvidenceRegistry:
    _entries: dict[str, EvidenceEntry] = field(default_factory=dict)

    @property
    def entries(self) -> tuple[EvidenceEntry, ...]:
        return tuple(item.model_copy(deep=True) for item in self._entries.values())

    def get(self, evidence_id: str) -> EvidenceEntry:
        if evidence_id not in self._entries:
            raise ValueError(
                f"Unknown evidence ID: {evidence_id}. Available IDs: {list(self._entries)}"
            )
        return self._entries[evidence_id].model_copy(deep=True)

    def retain(self, entries: list[EvidenceEntry]) -> None:
        for entry in entries:
            existing = self._entries.get(entry.evidence_id)
            if existing is not None and existing != entry:
                raise ValueError("Evidence ID collision with changed contents.")
            self._entries[entry.evidence_id] = entry.model_copy(deep=True)

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
        self.retain(
            [
                EvidenceEntry(
                    evidence_id=evidence_id,
                    kind=kind,
                    payload_json=canonical(data),
                    citation=citation,
                    borrower_id=borrower_id,
                    ticker=ticker,
                    period_end=period_end,
                    information_cutoff=information_cutoff,
                )
            ]
        )

    def _financial(self, financial: FinancialPeriod, cutoff: str) -> None:
        if financial.available_at is not None and financial.available_at > date.fromisoformat(
            cutoff
        ):
            raise ValueError("Financial evidence exceeds the information cutoff.")
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
        if isinstance(outcome, (RiskAssessment, FinancialReview)):
            if borrower_id is None or outcome.borrower_id != borrower_id:
                raise ValueError("Executed evidence is outside the configured borrower scope.")
            period, cutoff = str(outcome.period_end), str(outcome.information_cutoff)
            if isinstance(outcome, FinancialReview):
                if outcome.current and outcome.current.period_end != outcome.period_end:
                    raise ValueError(
                        "Current financial evidence uses a different reporting period."
                    )
                if any(item.period_end >= outcome.period_end for item in outcome.history):
                    raise ValueError("Financial history must precede the reporting period.")
                for financial in ([outcome.current] if outcome.current else []) + outcome.history:
                    if (
                        financial.borrower_id != borrower_id
                        or financial.period_end > outcome.period_end
                    ):
                        raise ValueError(
                            "Financial evidence has inconsistent borrower/period identity."
                        )
                    self._financial(financial, cutoff)
            else:
                data = outcome.model_dump(mode="json", exclude={"narrative", "results", "history"})
                self._add(
                    f"assessment:{outcome.assessment_run_id}",
                    "assessment",
                    data,
                    f"assessment {outcome.assessment_run_id}",
                    borrower_id,
                    period_end=period,
                    information_cutoff=cutoff,
                )
                for current, results in ((True, outcome.results), (False, outcome.history)):
                    for result in results:
                        if (
                            result.borrower_id != borrower_id
                            or result.assessment_run_id != outcome.assessment_run_id
                            or result.information_cutoff != outcome.information_cutoff
                            or (current and result.period_end != outcome.period_end)
                            or (not current and result.period_end >= outcome.period_end)
                        ):
                            raise ValueError(
                                "Calculation evidence has inconsistent identity or dates."
                            )
                        calculation = result.model_dump(mode="json")
                        calculation["presentation"] = calculation_details(calculation)
                        self._add(
                            f"calculation:{outcome.assessment_run_id}:{result.result_id}",
                            "calculation",
                            calculation,
                            f"assessment {outcome.assessment_run_id}, result {result.result_id}",
                            borrower_id,
                            period_end=str(result.period_end),
                            information_cutoff=cutoff,
                        )
                        raw = result.financial_inputs.get("financial_period")
                        if raw:
                            financial = FinancialPeriod.model_validate(raw)
                            if (
                                financial.borrower_id != borrower_id
                                or financial.period_end != result.period_end
                            ):
                                raise ValueError(
                                    "Calculation financial inputs have inconsistent scope."
                                )
                            self._financial(financial, cutoff)
                if outcome.prediction:
                    prediction = outcome.prediction
                    if (
                        prediction.borrower_id != borrower_id
                        or prediction.period_end != outcome.period_end
                        or outcome.feature_snapshot is None
                        or prediction.snapshot_id != outcome.feature_snapshot.snapshot_id
                        or prediction.prediction_status != outcome.ml_status
                    ):
                        raise ValueError("Prediction identity does not match its assessment.")
                    if prediction.prediction_status != "complete" and any(
                        value is not None
                        for value in (
                            prediction.breach_probability,
                            prediction.deterioration_probability,
                            prediction.anomaly_score,
                        )
                    ):
                        raise ValueError(
                            "Unavailable predictions cannot supply probabilities/scores."
                        )
                    self._add(
                        f"prediction:{prediction.prediction_id}",
                        "prediction",
                        prediction.model_dump(mode="json"),
                        f"assessment {outcome.assessment_run_id}, "
                        f"prediction {prediction.prediction_id}",
                        borrower_id,
                        period_end=period,
                        information_cutoff=cutoff,
                    )
        elif isinstance(outcome, list):
            for record in outcome:
                if isinstance(record, RetrievedRecord):
                    if ticker and record.ticker not in (None, ticker):
                        raise ValueError("Retrieved evidence is outside the issuer scope.")
                    cursor = 0
                    for block in re.split(r"\n\s*\n", record.text):
                        text = block.strip()
                        start = record.text.find(text, cursor) if text else cursor
                        cursor = start + len(text)
                        if not text or all(line.startswith("#") for line in text.splitlines()):
                            continue
                        # Instruction-only source paragraphs remain in the raw trace, not
                        # in the set of financial passages the answer may quote.
                        if re.search(
                            r"\bSYSTEM OVERRIDE\b|ignore (?:all |prior |previous )?instructions",
                            text,
                            re.I,
                        ):
                            continue
                        data = record.model_dump(mode="json")
                        data.update(
                            text=text,
                            excerpt_start=start,
                            excerpt_end=cursor,
                            excerpt_coordinate_system="returned_text",
                        )
                        identifier = hashlib.sha256(canonical(data).encode()).hexdigest()[:20]
                        self._add(
                            f"filing:{identifier}",
                            "filing",
                            data,
                            f"{record.document_id}: {record.citation}",
                            ticker=ticker or record.ticker,
                            period_end=record.period_end,
                        )
        elif isinstance(outcome, DocumentExtraction) and outcome.status == "complete":
            data = outcome.model_dump(mode="json")
            identifier = hashlib.sha256(canonical(data).encode()).hexdigest()[:20]
            self._add(
                f"filing:{identifier}",
                "filing",
                data,
                f"{outcome.document_id}: {outcome.citation}",
                ticker=ticker,
            )

    def prompt(self) -> str:
        return canonical(
            [
                {
                    "evidence_id": e.evidence_id,
                    "kind": e.kind,
                    "borrower_id": e.borrower_id,
                    "ticker": e.ticker,
                    "period_end": e.period_end,
                    "information_cutoff": e.information_cutoff,
                    "data": e.data,
                }
                for e in self.entries
            ]
        )

    def record_review(
        self, review: CreditReviewResult, *, borrower_id: str, assessment_run_id: str
    ) -> None:
        if (
            review.snapshot.borrower_id != borrower_id
            or review.snapshot.assessment_run_id != assessment_run_id
        ):
            raise ValueError("Saved review does not belong to the selected assessment.")
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
