"""Portfolio discovery and explicit runs over the existing assessment/review services."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.credit_review_service import CreditReviewService
from credit_monitoring.application.follow_up_question_service import FollowUpQuestionService
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult, ExposureDecisionContext
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.persistence.portfolio_repository import PortfolioRepository
from credit_monitoring.persistence.workflow_repository import WorkflowRepository

STATUS_LABELS = {
    "compliant": "Compliant",
    "breach": "Breach",
    "waived": "Waived",
    "not_tested": "Not tested",
    "incomplete": "Incomplete",
    "unresolved": "Unresolved",
    "unsupported": "Unsupported",
}
GAP_STATUSES = {"incomplete", "unresolved", "unsupported"}


@dataclass(frozen=True)
class PortfolioEntry:
    borrower_id: str
    name: str
    sector: str
    period_end: date | None
    assessment: RiskAssessment | None = None
    created_at: str | None = None
    review: CreditReviewResult | None = None
    last_error: str | None = None
    needs_review: bool = False

    @property
    def statuses(self) -> set[str]:
        return (
            {result.compliance_status for result in self.assessment.results}
            if self.assessment
            else set()
        )

    @property
    def compliance(self) -> str:
        if self.assessment is None:
            return "Not assessed"
        if not self.statuses:
            return "Incomplete"
        return " / ".join(STATUS_LABELS[status] for status in sorted(self.statuses))

    @property
    def needs_data(self) -> bool:
        return bool(
            self.assessment
            and (
                not self.statuses
                or self.statuses & GAP_STATUSES
                or not self.assessment.verification.is_valid
            )
        )


@dataclass(frozen=True)
class PortfolioOutcome:
    borrower_id: str
    period_end: date | None
    assessment: RiskAssessment | None = None
    error: str | None = None
    review: CreditReviewResult | None = None
    review_error: str | None = None
    follow_up_error: str | None = None


class PortfolioService:
    def __init__(
        self,
        *,
        borrowers: list[dict[str, str]],
        financial_repository: FinancialRepository,
        assessment_service: AssessmentService,
        review_service: CreditReviewService,
        repository: PortfolioRepository,
        workflow_repository: WorkflowRepository,
        follow_up_service: FollowUpQuestionService | None = None,
    ):
        self.borrowers = sorted(borrowers, key=lambda borrower: borrower["borrower_name"])
        self.financial_repository = financial_repository
        self.assessment_service = assessment_service
        self.review_service = review_service
        self.repository = repository
        self.workflow_repository = workflow_repository
        self.follow_up_service = follow_up_service
        self.follow_up_errors: dict[str, str] = {}

    def periods(self) -> list[date]:
        return sorted(
            {
                period.period_end
                for borrower in self.borrowers
                for period in self.financial_repository.get_period_history(borrower["borrower_id"])
            }
        )

    def target_period(self, borrower_id: str, period_end: date | None, cutoff: date) -> date | None:
        if period_end is not None:
            return period_end
        history = self.financial_repository.get_period_history(borrower_id, as_of=cutoff)
        return history[-1].period_end if history else None

    def snapshot(self, *, period_end: date | None, cutoff: date) -> list[PortfolioEntry]:
        self._validate_dates(period_end, cutoff)
        entries = []
        for borrower in self.borrowers:
            borrower_id = borrower["borrower_id"]
            target = self.target_period(borrower_id, period_end, cutoff)
            saved = (
                self.repository.latest_assessment(borrower_id, target, cutoff) if target else None
            )
            assessment, created_at = saved if saved else (None, None)
            entries.append(
                PortfolioEntry(
                    borrower_id=borrower_id,
                    name=borrower["borrower_name"],
                    sector=borrower["industry"],
                    period_end=target,
                    assessment=assessment,
                    created_at=created_at,
                    needs_review=self.workflow_repository.sources_changed_since(
                        borrower_id, created_at
                    )
                    if created_at
                    else False,
                    review=self.repository.latest_review(assessment.assessment_run_id)
                    if assessment
                    else None,
                    last_error=self.repository.latest_error(borrower_id, target, cutoff)
                    if target
                    else None,
                )
            )
        return entries

    @staticmethod
    def _validate_dates(period_end: date | None, cutoff: date) -> None:
        if period_end and cutoff < period_end:
            raise ValueError("Information cutoff must be on or after the reporting period.")

    def assess(
        self,
        borrower_ids: list[str],
        *,
        period_end: date | None,
        cutoff: date,
        progress: Callable[[int, int, PortfolioOutcome], None] | None = None,
        review_context: ExposureDecisionContext | None = None,
        stage_progress: Callable[[int, int, str, str], None] | None = None,
    ) -> list[PortfolioOutcome]:
        self._validate_dates(period_end, cutoff)
        known = {borrower["borrower_id"] for borrower in self.borrowers}
        selected = list(dict.fromkeys(borrower_ids))
        if not selected or set(selected) - known:
            raise ValueError("Choose at least one registered borrower.")
        if review_context is not None and not review_context.credit_criteria:
            raise ValueError("Supply at least one credit criterion for the agent reviews.")
        outcomes = []
        for index, borrower_id in enumerate(selected, 1):
            if stage_progress:
                stage_progress(index, len(selected), borrower_id, "Calculating covenants")
            target = self.target_period(borrower_id, period_end, cutoff)
            if target is None:
                outcome = PortfolioOutcome(
                    borrower_id, None, error="No financial periods are available at this cutoff."
                )
            else:
                try:
                    assessment = self.assessment_service.assess(borrower_id, target, cutoff)
                    self.repository.save_assessment(assessment)
                    outcome = PortfolioOutcome(borrower_id, target, assessment=assessment)
                except Exception as error:
                    # Retain an earlier successful run; do not leak provider/configuration details.
                    message = (
                        f"Assessment failed ({type(error).__name__}). "
                        "Previous saved results are retained."
                    )
                    self.repository.save_failure(borrower_id, target, cutoff, message)
                    outcome = PortfolioOutcome(borrower_id, target, error=message)
            if review_context is not None and outcome.assessment is not None:
                if stage_progress:
                    stage_progress(
                        index, len(selected), borrower_id, "Running credit review agents"
                    )
                try:
                    review = self.review(
                        outcome.assessment.assessment_run_id,
                        review_context,
                        follow_up_progress=(
                            lambda: stage_progress(
                                index, len(selected), borrower_id, "Generating follow-up questions"
                            )
                        )
                        if stage_progress
                        else None,
                    )
                    outcome = replace(
                        outcome,
                        review=review,
                        follow_up_error=self.follow_up_errors.get(review.review_id),
                    )
                except Exception as error:
                    outcome = replace(
                        outcome,
                        review_error=f"Agent review failed ({type(error).__name__}). "
                        "The assessment is saved; other borrowers will continue.",
                    )
            outcomes.append(outcome)
            if progress:
                progress(index, len(selected), outcome)
        return outcomes

    def review(
        self,
        run_id: str,
        context: ExposureDecisionContext,
        *,
        follow_up_progress: Callable[[], None] | None = None,
    ) -> CreditReviewResult:
        if not context.credit_criteria:
            raise ValueError("Supply at least one credit criterion for the agent review.")
        assessment = self.repository.get_assessment(run_id)
        review = self.review_service.review_assessment(assessment, decision_context=context)
        self.repository.save_review(review)
        if follow_up_progress:
            follow_up_progress()
        self.generate_follow_ups(assessment, review)
        return review

    def generate_follow_ups(self, assessment: RiskAssessment, review: CreditReviewResult) -> None:
        """A question-generation failure never discards an already saved review."""
        if self.follow_up_service is None:
            return
        try:
            self.follow_up_service.generate(assessment, review)
            self.follow_up_errors.pop(review.review_id, None)
        except Exception as error:
            self.follow_up_errors[review.review_id] = (
                f"Follow-up questions unavailable ({type(error).__name__}). "
                "The analysis is saved. Retry from the assistant."
            )
