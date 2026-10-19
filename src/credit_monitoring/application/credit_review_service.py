"""Application-controlled fan-out/fan-in review of one completed borrower assessment."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from credit_monitoring.agents.credit_review import (
    BearishCreditAgent,
    BullishCreditAgent,
    CreditRecommendationAgent,
)
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.review_evidence import build_review_snapshot
from credit_monitoring.domain.analytics_base import new_identifier
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import (
    CreditRecommendation,
    CreditReviewEvent,
    CreditReviewResult,
    ExposureDecisionContext,
    PerspectiveResult,
    ReviewAction,
    ReviewExecution,
    ReviewSnapshot,
)
from credit_monitoring.observability.logging import log_event
from credit_monitoring.public_context.events import PublicNewsContext
from credit_monitoring.public_context.retrieval import (
    PublicNewsProvider,
    UnavailableNewsProvider,
    filter_news,
)

logger = logging.getLogger(__name__)
type ReviewEventHandler = Callable[[CreditReviewEvent], Awaitable[None]]


def _sync[T](factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    raise RuntimeError("An event loop is already running; use the asynchronous review method.")


def _defer(reasons: list[str]) -> CreditRecommendation:
    return CreditRecommendation(
        action="defer",
        rationale="A supported credit recommendation is unavailable. " + " ".join(reasons),
        diligence_questions=("Resolve the reported evidence or review gaps.",),
        unresolved_uncertainties=tuple(reasons),
        confidence="low",
        confidence_explanation="Required evidence, criteria, or agent analysis is missing.",
    )


@dataclass
class _ReviewProgress:
    review_id: str
    assessment_run_id: str
    handler: ReviewEventHandler | None
    issues: list[str] = field(default_factory=list)

    async def emit(self, kind: str, stage: str, error_code: str | None = None) -> None:
        event = CreditReviewEvent(
            review_id=self.review_id,
            assessment_run_id=self.assessment_run_id,
            kind=kind,
            stage=stage,
            error_code=error_code,
        )
        log_event(logger, "credit_review", status=kind, outputs=event.model_dump(mode="json"))
        if self.handler is not None:
            try:
                await self.handler(event)
            except Exception as error:
                self.issues.append(f"Progress callback failed: {type(error).__name__}.")

    def record(self, execution: ReviewExecution) -> None:
        log_event(
            logger,
            "credit_review_agent",
            outputs={
                "review_id": self.review_id,
                **execution.model_dump(mode="json"),
            },
        )


def _deferral_reasons(
    assessment: RiskAssessment,
    context: ExposureDecisionContext | None,
    perspectives: tuple[PerspectiveResult, PerspectiveResult],
) -> list[str]:
    reasons = []
    if context is None or not context.credit_criteria:
        reasons.append("Analyst credit criteria were not supplied.")
    if not assessment.results:
        reasons.append("No current covenant results are available.")
    for perspective in perspectives:
        if perspective.analysis is None:
            reasons.append(
                f"The {perspective.perspective} review failed: {perspective.execution.error_code}."
            )
    if not any(item.analysis and item.analysis.arguments for item in perspectives):
        reasons.append("Neither perspective supplied supported arguments.")
    return reasons


class CreditReviewService:
    """Own scheduling and advisory-action boundaries; agents own analytical explanations."""

    def __init__(
        self,
        *,
        bullish_agent: BullishCreditAgent,
        bearish_agent: BearishCreditAgent,
        recommendation_agent: CreditRecommendationAgent,
        assessment_service: AssessmentService | None = None,
        news_provider: PublicNewsProvider | None = None,
        event_handler: ReviewEventHandler | None = None,
    ) -> None:
        self.bullish_agent = bullish_agent
        self.bearish_agent = bearish_agent
        self.recommendation_agent = recommendation_agent
        self.assessment_service = assessment_service
        self.news_provider = news_provider or UnavailableNewsProvider()
        self.event_handler = event_handler

    def review_assessment(
        self, assessment: RiskAssessment, *, decision_context: ExposureDecisionContext | None = None
    ) -> CreditReviewResult:
        return _sync(
            lambda: self.review_assessment_async(assessment, decision_context=decision_context)
        )

    def review(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        *,
        decision_context: ExposureDecisionContext | None = None,
        ml_enabled: bool | None = None,
    ) -> CreditReviewResult:
        return _sync(
            lambda: self.review_async(
                borrower_id,
                period_end,
                information_cutoff,
                decision_context=decision_context,
                ml_enabled=ml_enabled,
            )
        )

    async def review_async(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        *,
        decision_context: ExposureDecisionContext | None = None,
        ml_enabled: bool | None = None,
    ) -> CreditReviewResult:
        if self.assessment_service is None:
            raise ValueError("Configure an assessment service or review an existing assessment.")
        assessment = await asyncio.to_thread(
            self.assessment_service.assess,
            borrower_id,
            period_end,
            information_cutoff,
            ml_enabled=ml_enabled,
        )
        return await self.review_assessment_async(assessment, decision_context=decision_context)

    async def review_assessment_async(
        self, assessment: RiskAssessment, *, decision_context: ExposureDecisionContext | None = None
    ) -> CreditReviewResult:
        # Capture caller-owned mutable objects before any awaits or parallel work.
        assessment = RiskAssessment.model_validate(assessment.model_dump())
        if decision_context is not None:
            decision_context = ExposureDecisionContext.model_validate(decision_context.model_dump())
        progress = _ReviewProgress(
            new_identifier(), assessment.assessment_run_id, self.event_handler
        )
        unavailable = PublicNewsContext(
            borrower_id=assessment.borrower_id,
            information_cutoff=assessment.information_cutoff,
            status="unavailable",
            issues=("News retrieval was not performed.",),
        )
        snapshot, verification_errors = build_review_snapshot(assessment, unavailable)
        bullish = PerspectiveResult(
            perspective="bullish", execution=self.bullish_agent.skipped("verification_failed")
        )
        bearish = PerspectiveResult(
            perspective="bearish", execution=self.bearish_agent.skipped("verification_failed")
        )
        recommendation_execution = self.recommendation_agent.skipped("verification_failed")
        if verification_errors:
            progress.issues.extend(verification_errors)
            status, recommendation = "blocked", _defer(progress.issues)
        else:
            news = await self._news(assessment, progress)
            snapshot, _ = build_review_snapshot(assessment, news)
            bullish, bearish = await asyncio.gather(
                self._perspective(self.bullish_agent, snapshot, decision_context, progress),
                self._perspective(self.bearish_agent, snapshot, decision_context, progress),
            )
            defer_reasons = _deferral_reasons(assessment, decision_context, (bullish, bearish))
            progress.issues.extend(defer_reasons)
            recommendation, recommendation_execution = await self._recommendation(
                snapshot, decision_context, (bullish, bearish), defer_reasons, progress
            )
            status = (
                "incomplete"
                if (
                    bullish.analysis is None
                    or bearish.analysis is None
                    or recommendation_execution.status != "complete"
                )
                else "complete"
            )
        await progress.emit(
            "review_complete", "review", "verification_failed" if status == "blocked" else None
        )
        return CreditReviewResult(
            review_id=progress.review_id,
            snapshot=snapshot,
            decision_context=decision_context,
            bullish=bullish,
            bearish=bearish,
            recommendation=recommendation,
            recommendation_execution=recommendation_execution,
            status=status,
            issues=tuple(dict.fromkeys((*snapshot.limitations, *progress.issues))),
        )

    async def _news(
        self, assessment: RiskAssessment, progress: _ReviewProgress
    ) -> PublicNewsContext:
        await progress.emit("stage_start", "news")
        try:
            async with asyncio.timeout(self.recommendation_agent.settings.timeout_seconds):
                news = filter_news(
                    await self.news_provider.get_context(
                        assessment.borrower_id, assessment.information_cutoff
                    ),
                    assessment.borrower_id,
                    assessment.information_cutoff,
                )
        except Exception as error:
            news = PublicNewsContext(
                borrower_id=assessment.borrower_id,
                information_cutoff=assessment.information_cutoff,
                status="failed",
                issues=(f"Public news retrieval failed: {type(error).__name__}.",),
            )
        await progress.emit(
            "stage_failed" if news.status == "failed" else "stage_complete",
            "news",
            "news_unavailable" if news.status == "failed" else None,
        )
        return news

    async def _perspective(
        self,
        agent: BullishCreditAgent | BearishCreditAgent,
        snapshot: ReviewSnapshot,
        context: ExposureDecisionContext | None,
        progress: _ReviewProgress,
    ) -> PerspectiveResult:
        await progress.emit("stage_start", agent.role)
        result = await agent.assess_async(snapshot, context)
        progress.record(result.execution)
        await progress.emit(
            "stage_complete" if result.analysis is not None else "stage_failed",
            agent.role,
            result.execution.error_code,
        )
        return result

    async def _recommendation(
        self,
        snapshot: ReviewSnapshot,
        context: ExposureDecisionContext | None,
        perspectives: tuple[PerspectiveResult, PerspectiveResult],
        reasons: list[str],
        progress: _ReviewProgress,
    ) -> tuple[CreditRecommendation, ReviewExecution]:
        if all(item.analysis is None for item in perspectives):
            return _defer(reasons), self.recommendation_agent.skipped("reviewers_failed")
        allowed_actions: tuple[ReviewAction, ...] = (
            ("defer",) if reasons else ("maintain", "increase", "reduce", "review", "defer")
        )
        await progress.emit("stage_start", "recommendation")
        recommendation, execution = await self.recommendation_agent.recommend_async(
            snapshot, context, perspectives, allowed_actions
        )
        progress.record(execution)
        await progress.emit(
            "stage_complete" if recommendation else "stage_failed",
            "recommendation",
            execution.error_code,
        )
        if recommendation is None:
            progress.issues.append(f"The recommendation agent failed: {execution.error_code}.")
            recommendation = _defer(progress.issues)
        return recommendation, execution
