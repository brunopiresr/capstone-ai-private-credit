"""Borrower-scoped PydanticAI tools over the existing calculation and prediction workflow."""

from datetime import date

from pydantic_ai import Tool

from credit_monitoring.agents.tools.common import (
    InvalidToolArguments,
    ISODate,
    domain_tool,
)
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.domain.tool_results import FinancialReview


class AssessmentTools:
    """The application owns borrower scope, services, formulas, databases and model selection."""

    def __init__(self, service: AssessmentService, *, borrower_id: str) -> None:
        if not borrower_id.strip():
            raise ValueError("An explicit borrower ID is required for assessment tools.")
        self.service = service
        self.borrower_id = borrower_id

    @property
    def tools(self) -> list[Tool]:
        return [
            domain_tool(method)
            for method in (self.get_financials, self.assess_covenants, self.predict_risk)
        ]

    def get_financials(
        self,
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> FinancialReview:
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
            A financial review containing current metrics, earlier periods, source
            provenance, and missing-data or availability issues. No alternative
            reporting period is substituted.
        """
        period, cutoff = self._dates(period_end, information_cutoff)
        return self._financials(period, cutoff)

    def assess_covenants(
        self,
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> RiskAssessment:
        """Calculate and verify current covenant compliance and headroom.

        Use this for deterministic covenant assessments. The service resolves
        configured terms, applies established formulas, and persists results.
        This tool does not invoke ML.

        Args:
            period_end: The reporting date, formatted as YYYY-MM-DD.
            information_cutoff: The information cutoff, formatted as YYYY-MM-DD.
                It must be on or after period_end.

        Returns:
            A risk assessment containing ratios, applicable thresholds, compliance,
            headroom, verification, provenance, and run IDs. Missing inputs and
            unresolved terms remain explicit.
        """
        period, cutoff = self._dates(period_end, information_cutoff)
        return self.service.assess(self.borrower_id, period, cutoff, ml_enabled=False)

    def predict_risk(
        self,
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> RiskAssessment:
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
            A risk assessment containing covenant results, prediction status, supplied
            probabilities, the exact feature snapshot, and model metadata.
            Valid calculations are retained when prediction fails.
        """
        period, cutoff = self._dates(period_end, information_cutoff)
        return self.service.assess(self.borrower_id, period, cutoff, ml_enabled=True)

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

    def _financials(self, period_end: date, cutoff: date) -> FinancialReview:
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
        return FinancialReview(
            borrower_id=self.borrower_id,
            period_end=period_end,
            information_cutoff=cutoff,
            current=current,
            history=[item for item in periods if item.period_end < period_end],
            issues=issues,
        )
