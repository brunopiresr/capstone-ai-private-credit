"""Borrower-scoped PydanticAI tools over the existing calculation and prediction workflow."""

from datetime import date

from pydantic_ai import Tool

from credit_monitoring.agents.tools.common import (
    InvalidToolArguments,
    ISODate,
    domain_tool,
)
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.domain.assessment import RiskAssessment
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
        """Read source financial metrics and history before requesting calculations.

        Missing inputs and unknown availability remain explicit; no alternative
        reporting period is substituted.

        Args:
            period_end: Analyst-supplied reporting date, YYYY-MM-DD.
            information_cutoff: Analyst-supplied cutoff, YYYY-MM-DD;
                must be on or after period_end.

        Returns:
            Current metrics, earlier periods, provenance and availability issues.
        """
        period, cutoff = self._dates(period_end, information_cutoff)
        return self._financials(period, cutoff)

    def assess_covenants(
        self,
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> RiskAssessment:
        """Calculate and verify current covenant compliance and headroom.

        Resolve configured terms with established formulas; ML is disabled.
        First call get_financials with the same dates. One assess_covenants call
        supplies current and historical results; do not use it after predict_risk.
        Distinguish source-disclosed actuals from calculated values.

        Args:
            period_end: Analyst-supplied reporting date, YYYY-MM-DD.
            information_cutoff: Analyst-supplied cutoff, YYYY-MM-DD;
                must be on or after period_end.

        Returns:
            Calculations, applicability, provenance, run IDs and limitations.
            Verification covers structured results, not generated prose.
        """
        period, cutoff = self._dates(period_end, information_cutoff)
        return self._with_context(
            self.service.assess(self.borrower_id, period, cutoff, ml_enabled=False)
        )

    def predict_risk(
        self,
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> RiskAssessment:
        """Calculate current covenants and run the configured next-quarter model.

        Use for forecast requests. Keep the analyst's input dates unchanged;
        REQUIRED: call get_financials with those dates before calling this tool.
        This tool also supplies current compliance and history: answer from its
        result without another assess_covenants or predict_risk call.
        the service determines the forecast horizon. Distinguish predicted risk
        from current observed compliance and disclosed actuals from calculations.
        Report supplied model name/version, horizon, probability and snapshot_id.

        Args:
            period_end: Analyst-supplied reporting date, YYYY-MM-DD.
            information_cutoff: Analyst-supplied cutoff, YYYY-MM-DD;
                must be on or after period_end.

        Returns:
            Calculations, model output, provenance and applicable limitations.
            Verification covers structured results, not generated prose.
        """
        period, cutoff = self._dates(period_end, information_cutoff)
        return self._with_context(
            self.service.assess(self.borrower_id, period, cutoff, ml_enabled=True)
        )

    @staticmethod
    def _with_context(assessment: RiskAssessment) -> RiskAssessment:
        """Describe applicable limitations without mutating service-owned results."""
        result = assessment.model_copy(deep=True)
        caveats = []
        if result.ml_status == "stub":
            caveats.append(
                "The configured model is a stub; no forecast or risk probability is available."
            )
        elif result.ml_status in ("failed", "unavailable"):
            caveats.append(
                "Model output is unavailable; deterministic results retain their reported status."
            )
        elif (
            result.ml_status == "complete"
            and result.prediction is not None
            and result.prediction.model_name == "logistic_regression"
        ):
            caveats.append(
                "The Logistic Regression baseline was trained and evaluated on synthetic "
                "borrower histories, not real credit outcomes."
            )
        if any(
            issue.code == "information_availability_unknown" for issue in result.verification.issues
        ) or (
            result.feature_snapshot is not None
            and not result.feature_snapshot.features.information_availability_known
        ):
            caveats.append(
                "Source availability dates are unknown; point-in-time forecast reliability "
                "is not established."
            )
        for caveat in caveats:
            if caveat not in result.issues:
                result.issues.append(caveat)
        return result

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
        history = self.service.financial_repository.get_period_history(
            self.borrower_id, as_of=period_end
        )
        periods, issues = [], []
        for financials in history:
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
