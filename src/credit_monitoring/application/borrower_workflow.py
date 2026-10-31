"""Analyst actions over saved portfolio versions; decisions never change compliance."""

from datetime import date
from pathlib import Path

from credit_monitoring.application.bootstrap import create_assessment_service
from credit_monitoring.application.portfolio_service import GAP_STATUSES, PortfolioService
from credit_monitoring.config.settings import (
    DEFAULT_APP_PREDICTION_MODE,
    AssessmentSettings,
    RiskModelConfig,
)
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.persistence.workflow_repository import WorkflowRepository

PREDICTION_MODES = ("Off", "Stub", "Logistic Regression")


class BorrowerWorkflow:
    def __init__(
        self, portfolio: PortfolioService, repository: WorkflowRepository, data_root: Path
    ):
        self.portfolio = portfolio
        self.repository = repository
        self.data_root = data_root

    def assess(
        self,
        borrower_id: str,
        period: date,
        cutoff: date,
        *,
        prediction_mode: str = DEFAULT_APP_PREDICTION_MODE,
        parent_id: str | None = None,
        reason: str = "",
        overrides: dict[str, float | None] | None = None,
        financial_snapshot: FinancialPeriod | None = None,
    ) -> RiskAssessment:
        if borrower_id not in {b["borrower_id"] for b in self.portfolio.borrowers}:
            raise ValueError("Choose a registered borrower.")
        if prediction_mode not in PREDICTION_MODES:
            raise ValueError("Unknown prediction mode.")
        if parent_id:
            parent = self.portfolio.repository.get_assessment(parent_id)
            if parent.borrower_id != borrower_id or parent.period_end != period:
                raise ValueError("The parent must belong to the same borrower and period.")
            if not reason.strip():
                raise ValueError("Record a reason for recalculation.")
            if overrides is not None:
                current = SavedFinancials(parent).get_period_history(borrower_id, as_of=period)
                saved = next((p for p in current if p.period_end == period), None)
                if saved:
                    overrides = {**saved.metrics, **overrides}
        elif overrides is not None or financial_snapshot is not None:
            raise ValueError("Revise a saved assessment before supplying changed inputs.")
        base = self.portfolio.assessment_service
        model = RiskModelConfig()
        if prediction_mode == "Logistic Regression":
            model = RiskModelConfig(
                type="logistic_regression",
                artifact_path=self.data_root / "models" / "logistic_regression" / "v1",
            )
        service = create_assessment_service(
            financial_repository=base.financial_repository,
            covenant_reader=base.covenant_reader,
            settings=AssessmentSettings(
                analytics_database=base.settings.analytics_database,
                ml_enabled=prediction_mode != "Off",
                risk_model=model,
            ),
        )
        assessment = service.assess(
            borrower_id,
            period,
            cutoff,
            financial_overrides=overrides,
            revision_reason=reason,
            financial_snapshot=financial_snapshot,
        )
        self.portfolio.repository.save_assessment(assessment)
        self.repository.record(
            assessment.assessment_run_id,
            borrower_id,
            "run",
            {
                "parent_id": parent_id,
                "reason": reason.strip(),
                "prediction_mode": prediction_mode,
                "overrides": overrides,
            },
        )
        return assessment

    def enable_ml(self, run_id: str) -> RiskAssessment:
        assessment = self.portfolio.repository.get_assessment(run_id)
        periods = SavedFinancials(assessment).get_period_history(
            assessment.borrower_id, as_of=assessment.period_end
        )
        current = next((p for p in periods if p.period_end == assessment.period_end), None)
        return self.assess(
            assessment.borrower_id,
            assessment.period_end,
            assessment.information_cutoff,
            prediction_mode=DEFAULT_APP_PREDICTION_MODE,
            parent_id=run_id,
            reason="Enable the bundled Logistic Regression forecast.",
            financial_snapshot=current,
        )

    def validation(self, run_id: str) -> dict | None:
        if self.needs_review(run_id):
            return None
        events = self.repository.events(run_id, "validation")
        if not events:
            return None
        review = self.portfolio.repository.latest_review(run_id)
        if events[0]["payload"]["review_id"] != (review.review_id if review else None):
            return None
        return events[0]

    def needs_review(self, run_id: str) -> bool:
        assessment = self.portfolio.repository.get_assessment(run_id)
        return self.repository.sources_changed_since(
            assessment.borrower_id, self.portfolio.repository.assessment_created_at(run_id)
        )

    @staticmethod
    def needs_exceptions(assessment: RiskAssessment) -> bool:
        return not assessment.results or any(
            r.compliance_status in GAP_STATUSES for r in assessment.results
        )

    def validate(
        self, run_id: str, *, checks: tuple[bool, bool, bool], notes: str, analyst: str = ""
    ) -> None:
        assessment = self.portfolio.repository.get_assessment(run_id)
        if self.needs_review(run_id):
            raise ValueError("Sources changed after this assessment. Reassess before validating.")
        if not assessment.verification.is_valid or any(
            i.severity == "error" for i in assessment.verification.issues
        ):
            raise ValueError("Resolve structured verification errors before validation.")
        if len(checks) != 3 or not all(checks):
            raise ValueError("Complete all three review checks before validation.")
        if self.needs_exceptions(assessment) and not notes.strip():
            raise ValueError("Document the missing data and unresolved exceptions.")
        review = self.portfolio.repository.latest_review(run_id)
        self.repository.record(
            run_id,
            assessment.borrower_id,
            "validation",
            {
                "checks": checks,
                "notes": notes.strip(),
                "analyst": analyst.strip(),
                "with_exceptions": self.needs_exceptions(assessment),
                "review_id": review.review_id if review else None,
            },
        )

    def flag(
        self, run_id: str, *, category: str, severity: str, explanation: str, action: str
    ) -> str:
        assessment = self.portfolio.repository.get_assessment(run_id)
        if not category.strip() or not explanation.strip():
            raise ValueError("Supply a category and short explanation for the flag.")
        if severity not in {"Low", "Medium", "High", "Critical"}:
            raise ValueError("Choose a supported severity.")
        return self.repository.add_flag(
            run_id,
            assessment.borrower_id,
            {
                "category": category.strip(),
                "severity": severity,
                "explanation": explanation.strip(),
                "action": action.strip(),
                "state": "open",
            },
        )

    def save_report(
        self, run_id: str, *, text: str, analyst: str = "", triage: str = "", submit: bool = False
    ) -> str | None:
        assessment = self.portfolio.repository.get_assessment(run_id)
        if not text.strip():
            raise ValueError("Add analyst observations before saving or submitting.")
        payload = {"text": text.strip(), "analyst": analyst.strip(), "triage": triage.strip()}
        if not submit:
            self.repository.record(run_id, assessment.borrower_id, "draft", payload)
            return None
        validation = self.validation(run_id)
        if not validation:
            raise ValueError("Validate this assessment and its current review before submitting.")
        flags = [
            f
            for f in self.repository.flags(assessment.borrower_id)
            if f["payload"]["state"] == "open"
        ]
        # An older flag stays open but does not automatically triage a new breach version.
        current_flags = [f for f in flags if f["run_id"] == run_id]
        if any(r.compliance_status == "breach" for r in assessment.results):
            if not current_flags and not triage.strip():
                raise ValueError("Flag this breach version or explain the triage decision.")
        review = self.portfolio.repository.latest_review(run_id)
        return self.repository.submit(
            run_id,
            assessment.borrower_id,
            {
                **payload,
                "assessment": assessment.model_dump(mode="json"),
                "review_id": review.review_id if review else None,
                "review": review.model_dump(mode="json") if review else None,
                "validation": validation,
                "flags": flags,
                "state": "submitted",
            },
        )


class SavedFinancials:
    """Financial reads for chat come from the selected immutable assessment."""

    def __init__(self, assessment: RiskAssessment):
        self.assessment = assessment

    def get_period_history(self, borrower_id: str, *, as_of: date | None = None):
        if borrower_id != self.assessment.borrower_id:
            raise ValueError("Chat is scoped to the selected borrower.")
        periods = {}
        for result in self.assessment.history + self.assessment.results:
            raw = result.financial_inputs.get("financial_period")
            if raw:
                period = FinancialPeriod.model_validate(raw)
                if as_of is None or period.period_end <= as_of:
                    periods[period.period_end] = period
        return [periods[d] for d in sorted(periods)]


class SavedAssessmentChat:
    """Reuse existing agent tools, reading saved results unless recalculation is enabled."""

    def __init__(self, workflow: BorrowerWorkflow, assessment: RiskAssessment):
        self.workflow = workflow
        self.assessment = assessment
        self.financial_repository = SavedFinancials(assessment)
        self.allow_recalculation = False
        self.reason = ""
        self.prediction_mode = "Off"
        self.new_assessment: RiskAssessment | None = None

    def assess(self, borrower_id, period_end, information_cutoff, *, ml_enabled=None):
        saved = self.assessment
        if (borrower_id, period_end, information_cutoff) != (
            saved.borrower_id,
            saved.period_end,
            saved.information_cutoff,
        ):
            raise ValueError("Change the analysis selection to use other borrowers or dates.")
        if not self.allow_recalculation:
            if ml_enabled and saved.ml_status == "disabled":
                raise ValueError(
                    "Enable recalculation and choose a prediction mode for a forecast."
                )
            return saved.model_copy(deep=True)
        if self.new_assessment is None:
            periods = self.financial_repository.get_period_history(borrower_id, as_of=period_end)
            current = next((p for p in periods if p.period_end == period_end), None)
            self.new_assessment = self.workflow.assess(
                borrower_id,
                period_end,
                information_cutoff,
                prediction_mode=self.prediction_mode if ml_enabled else "Off",
                parent_id=saved.assessment_run_id,
                reason=self.reason,
                overrides=current.metrics if current else None,
            )
        return self.new_assessment.model_copy(deep=True)
