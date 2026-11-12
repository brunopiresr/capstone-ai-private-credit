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
from credit_monitoring.domain.tool_results import (
    FinancialPeriodCatalog,
    FinancialPeriodSummary,
    FinancialReview,
)


class AssessmentTools:
    """The application owns borrower scope, services, formulas, databases and model selection."""

    def __init__(
        self,
        service: AssessmentService,
        *,
        borrower_id: str,
        selected_dates: tuple[date, date] | None = None,
    ) -> None:
        if not borrower_id.strip():
            raise ValueError("An explicit borrower ID is required for assessment tools.")
        self.service = service
        self.borrower_id = borrower_id
        self.selected_dates = selected_dates

    @property
    def tools(self) -> list[Tool]:
        return [
            domain_tool(method)
            for method in (
                self.list_financial_periods,
                self.get_financials,
                self.assess_covenants,
                self.predict_risk,
            )
        ]

    @property
    def data_source(self) -> dict:
        """Describe the active adapter without changing what that adapter can read."""
        selected = getattr(self.service, "assessment", None)
        if isinstance(selected, RiskAssessment):
            return {
                "source": "saved_assessment",
                "assessment_run_id": selected.assessment_run_id,
                "period_end": selected.period_end.isoformat(),
                "information_cutoff": selected.information_cutoff.isoformat(),
            }
        return {"source": "financial_repository", "assessment_run_id": None}

    def list_financial_periods(self) -> FinancialPeriodCatalog:
        """Discover stored reporting periods and known availability for the selected borrower.

        Requires no dates. Returns metadata without metrics or calculations. Use
        it when the reporting period is not yet known. A saved-assessment source
        contains only that snapshot and its history, not the live financial database.
        Unknown availability stays null; storage/load timestamps are not publication dates.

        Returns:
            Selected borrower, ordered periods/availability, and active source identity.
            An empty periods list means no financial periods are stored in that source.
        """
        source = self.data_source
        periods = self.service.financial_repository.get_period_history(self.borrower_id)
        return FinancialPeriodCatalog(
            borrower_id=self.borrower_id,
            source=source["source"],
            source_assessment_run_id=source["assessment_run_id"],
            periods=[
                FinancialPeriodSummary(period_end=p.period_end, available_at=p.available_at)
                for p in sorted(periods, key=lambda p: p.period_end)
            ],
        )

    def get_financials(
        self,
        period_end: ISODate,
        information_cutoff: ISODate,
    ) -> FinancialReview:
        """Read source financial metrics and history for an explicit reporting period and cutoff.

        Use when the question needs raw inputs. This read performs no calculations
        and does not require a subsequent assessment. The calculation and prediction
        tools load their own financials, so this is optional for those operations.
        Missing inputs and unknown availability remain explicit; no alternative
        reporting period is substituted.

        Args:
            period_end: Unambiguous reporting period, YYYY-MM-DD, from request/context
                or period discovery. Ask before choosing among multiple possible interpretations.
            information_cutoff: Information window end, YYYY-MM-DD, on or after period_end.
                Preserve the user's/contextual cutoff. For latest/current analysis only,
                a missing cutoff may default to the supplied current_date; disclose it.
                A historical period without a cutoff requires clarification.

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
        """Load financials, calculate and verify current covenant compliance and headroom.

        ML is disabled. This standalone operation reads its own inputs and returns
        current and historical calculations, terms, verification and gaps. A separate
        financial read is optional. Distinguish reported facts from calculated values.

        Args:
            period_end: Unambiguous reporting period, YYYY-MM-DD, from request/context
                or period discovery. Ask before choosing among multiple possible interpretations.
            information_cutoff: Information window end, YYYY-MM-DD, on or after period_end.
                Preserve the user's/contextual cutoff. For latest/current analysis only,
                a missing cutoff may default to the supplied current_date; disclose it.
                A historical period without a cutoff requires clarification.

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
        """Load financials, assess current covenants and run the configured forecast model.

        Use when a forecast is requested. This standalone operation includes current
        compliance and history; separate financial reads and assessments are optional.
        Pass the base reporting period and cutoff, not the future target quarter.
        The service determines the forecast horizon. Distinguish predicted risk from
        current observed compliance and disclosed actuals from calculations.
        Model metadata, snapshot identity, unavailable outputs and limitations are
        returned explicitly; verification covers structured results, not generated prose.

        Args:
            period_end: Unambiguous reporting period, YYYY-MM-DD, from request/context
                or period discovery. Ask before choosing among multiple possible interpretations.
            information_cutoff: Information window end, YYYY-MM-DD, on or after period_end.
                Preserve the user's/contextual cutoff. For latest/current analysis only,
                a missing cutoff may default to the supplied current_date; disclose it.
                A historical period without a cutoff requires clarification.

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

    def _dates(self, period_end: str, information_cutoff: str) -> tuple[date, date]:
        try:
            period = date.fromisoformat(period_end)
            cutoff = date.fromisoformat(information_cutoff)
        except ValueError as exc:
            raise InvalidToolArguments(str(exc)) from exc
        if self.selected_dates is not None and (period, cutoff) != self.selected_dates:
            selected_period, selected_cutoff = self.selected_dates
            raise InvalidToolArguments(
                f"Use the selected period_end={selected_period} and "
                f"information_cutoff={selected_cutoff}. Predictions use these base dates; "
                "the service determines the future forecast quarter."
            )
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
