"""Borrower-scoped SDK tools over the existing calculation and prediction workflow."""

import json
from datetime import date

from agents import FunctionTool, function_tool
from agents.tool_context import ToolContext

from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.common import (
    InvalidToolArguments,
    ISODate,
    tool_error,
    tool_result,
    validate_call,
)
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment


class AssessmentTools:
    """The application owns borrower scope, services, formulas, databases and model selection."""

    def __init__(self, service: AssessmentService, *, borrower_id: str) -> None:
        if not borrower_id.strip():
            raise ValueError("An explicit borrower ID is required for assessment tools.")
        self.service = service
        self.borrower_id = borrower_id

    @property
    def tools(self) -> list[FunctionTool]:
        return [
            function_tool(method, failure_error_function=tool_error)
            for method in (self.get_financials, self.assess_covenants, self.predict_risk)
        ]

    def get_financials(
        self,
        ctx: ToolContext[AgentRunState],
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> str:
        """Read source financial metrics and history for the borrower.

        Use this to inspect inputs before requesting calculations. Borrower
        scope comes from the application. Obtain both dates from the analyst;
        do not substitute today's date.

        Args:
            period_end: The financial reporting period used as input, formatted
                as YYYY-MM-DD. Use the analyst's reporting date, not a future
                forecast date.
            information_cutoff: The information cutoff, formatted as YYYY-MM-DD.
                It must be on or after period_end.

        Returns:
            JSON containing current financial metrics, earlier periods, source
            provenance, and missing-data or availability issues. No alternative
            reporting period is substituted.
        """
        validate_call(ctx, self.get_financials)
        period, cutoff = self._dates(period_end, information_cutoff)
        return json.dumps(self._financials(period, cutoff), ensure_ascii=False)

    def assess_covenants(
        self,
        ctx: ToolContext[AgentRunState],
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> str:
        """Calculate and verify current covenant compliance and headroom.

        Use this for deterministic covenant assessments. The service resolves
        configured terms, applies established formulas, and persists results.
        This tool does not invoke ML.

        Args:
            period_end: The reporting date, formatted as YYYY-MM-DD.
            information_cutoff: The information cutoff, formatted as YYYY-MM-DD.
                It must be on or after period_end.

        Returns:
            JSON containing calculated ratios, applicable thresholds, compliance,
            headroom, verification, provenance, and run IDs. Missing inputs and
            unresolved terms remain explicit.
        """
        validate_call(ctx, self.assess_covenants)
        period, cutoff = self._dates(period_end, information_cutoff)
        assessment = self.service.assess(self.borrower_id, period, cutoff, ml_enabled=False)
        return self._assessment_result(assessment)

    def predict_risk(
        self,
        ctx: ToolContext[AgentRunState],
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> str:
        """Run covenant calculations and the configured risk model.

        Use this when the analyst requests a forecast. Report current observed
        compliance separately from the next-quarter prediction. The application
        selects the model; a stub supplies no forecast.
        Keep the analyst's input dates unchanged from the current assessment.
        The service handles the forecast horizon; do not advance either date.

        Args:
            period_end: The financial reporting period used as input, formatted
                as YYYY-MM-DD. Use the analyst's reporting date, not a future
                forecast date.
            information_cutoff: The information cutoff, formatted as YYYY-MM-DD.
                It must be on or after period_end.

        Returns:
            JSON containing covenant results, prediction status, supplied
            probabilities, the exact feature snapshot, and model metadata.
            Valid calculations are retained when prediction fails.
        """
        validate_call(ctx, self.predict_risk)
        period, cutoff = self._dates(period_end, information_cutoff)
        assessment = self.service.assess(self.borrower_id, period, cutoff, ml_enabled=True)
        return self._assessment_result(assessment)

    @staticmethod
    def _dates(period_end: str, information_cutoff: str) -> tuple[date, date]:
        try:
            period = date.fromisoformat(period_end)
            cutoff = date.fromisoformat(information_cutoff)
        except ValueError as exc:
            raise InvalidToolArguments(str(exc)) from exc
        if cutoff < period:
            raise InvalidToolArguments("Information cutoff must be on or after the reporting date.")
        return period, cutoff

    @staticmethod
    def _assessment_result(assessment: RiskAssessment) -> str:
        sources = [
            {"document_id": evidence["document_id"], "citation": evidence["citation"]}
            for result in assessment.results + assessment.history
            for evidence in result.evidence
            if evidence.get("document_id") and evidence.get("citation")
        ]
        return tool_result(assessment.model_dump(mode="json"), sources=sources)

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
