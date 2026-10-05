"""Borrower-scoped tools over the existing calculation and prediction workflow."""

import sqlite3
from datetime import date
from typing import Any

from pydantic import Field, ValidationError

from credit_monitoring.agents.tools.documents import ToolArguments
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.domain.assessment import FinancialPeriod


class AssessmentArguments(ToolArguments):
    period_end: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="Reporting date, YYYY-MM-DD."
    )
    information_cutoff: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Explicit information cutoff, YYYY-MM-DD; on or after the reporting date.",
    )


_TOOLS = {
    "get_financials": "Read source financial metrics and history for the scoped borrower.",
    "assess_covenants": (
        "Resolve configured covenant terms, calculate ratios, compliance and headroom, "
        "verify and persist results. Does not invoke ML."
    ),
    "predict_risk": (
        "Run verified covenant calculations and the application-configured ML model. "
        "Return current compliance separately from the next-quarter prediction, "
        "with exact feature snapshot and model metadata. A stub supplies no forecast."
    ),
}


class AssessmentTools:
    """Dates are model-supplied; borrower, formulas, database and model are application-owned."""

    def __init__(self, service: AssessmentService, *, borrower_id: str) -> None:
        if not borrower_id.strip():
            raise ValueError("An explicit borrower ID is required for assessment tools.")
        self.service = service
        self.borrower_id = borrower_id

    @property
    def definitions(self) -> list[dict]:
        return [
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": AssessmentArguments.model_json_schema(),
                "strict": True,
            }
            for name, description in _TOOLS.items()
        ]

    def supports(self, name: str) -> bool:
        return name in _TOOLS

    def execute(self, name: str, arguments: Any) -> dict:
        if name not in _TOOLS:
            return {"ok": False, "error": "unknown_tool", "message": f"Unknown tool: {name}"}
        try:
            args = AssessmentArguments.model_validate(arguments)
            period_end = date.fromisoformat(args.period_end)
            cutoff = date.fromisoformat(args.information_cutoff)
            if cutoff < period_end:
                raise ValueError("Information cutoff must be on or after the reporting date.")
        except (ValidationError, ValueError) as exc:
            return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
        try:
            if name == "get_financials":
                return self._financials(period_end, cutoff)
            assessment = self.service.assess(
                self.borrower_id, period_end, cutoff, ml_enabled=name == "predict_risk"
            )
            sources = []
            for result in assessment.results + assessment.history:
                for evidence in result.evidence:
                    if evidence.get("document_id") and evidence.get("citation"):
                        sources.append(
                            {
                                "document_id": evidence["document_id"],
                                "citation": evidence["citation"],
                            }
                        )
            # ML failures and abstentions remain in the typed outcome, alongside calculations.
            return {"ok": True, "data": assessment.model_dump(mode="json"), "sources": sources}
        except (OSError, ValueError, sqlite3.Error) as exc:
            return {"ok": False, "error": "service_error", "message": str(exc)}

    def _financials(self, period_end: date, cutoff: date) -> dict:
        rows = self.service.financial_repository.get_history(
            self.borrower_id, as_of=period_end.isoformat()
        )
        periods, issues = [], []
        for row in rows:
            financials = FinancialPeriod.from_repository_row(row)
            if financials.available_at is not None and financials.available_at > cutoff:
                issues.append(f"Financial inputs for {financials.period_end} exceed the cutoff.")
                continue
            periods.append(financials)
        current = next((item for item in periods if item.period_end == period_end), None)
        if current is None:
            issues.append("No financial inputs are available for the requested reporting date.")
        if any(item.available_at is None for item in periods):
            issues.append(
                "Source availability dates are unknown; load times are not publication dates."
            )
        return {
            "ok": True,
            "data": {
                "borrower_id": self.borrower_id,
                "period_end": period_end.isoformat(),
                "information_cutoff": cutoff.isoformat(),
                "current": current.model_dump(mode="json") if current else None,
                "history": [
                    item.model_dump(mode="json") for item in periods if item.period_end < period_end
                ],
                "issues": issues,
            },
            "sources": [],
        }
