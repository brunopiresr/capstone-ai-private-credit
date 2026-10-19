"""Public review contracts: evidence-backed explanations and application-owned execution."""

import json
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from credit_monitoring.public_context.events import PublicNewsContext

from .analytics_base import AssessmentModel, new_identifier, utc_now

type Nonblank = Annotated[str, Field(min_length=1)]
type Perspective = Literal["bullish", "bearish"]
type ReviewRole = Literal["bullish", "bearish", "recommendation"]
type EvidenceConfidence = Literal["low", "medium", "high"]
type ReviewAction = Literal["maintain", "increase", "reduce", "review", "defer"]


class ReviewModel(AssessmentModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


class ExposureDecisionContext(ReviewModel):
    question: Nonblank
    credit_criteria: tuple[Nonblank, ...] = ()
    constraints: tuple[Nonblank, ...] = ()


class EvidenceReference(ReviewModel):
    evidence_id: Nonblank
    kind: Literal[
        "assessment",
        "calculation",
        "financial",
        "source",
        "trends",
        "features",
        "prediction",
        "news",
    ]
    path: Nonblank = Field(description="JSON pointer into the shared prompt context.")


class ReviewSnapshot(ReviewModel):
    """Canonical JSON and immutable records prevent mutation between parallel reviewers."""

    borrower_id: Nonblank
    assessment_run_id: Nonblank
    period_end: date
    information_cutoff: date
    assessment_json: str = Field(
        description="Sanitized assessment; no generated narrative or notes."
    )
    news: PublicNewsContext
    evidence: tuple[EvidenceReference, ...]
    limitations: tuple[str, ...] = ()

    @property
    def assessment_data(self) -> dict:
        """Return an isolated view; changes never modify the frozen snapshot."""
        return json.loads(self.assessment_json)

    def prompt_context(self) -> dict:
        return {
            "borrower_id": self.borrower_id,
            "assessment_run_id": self.assessment_run_id,
            "period_end": self.period_end.isoformat(),
            "information_cutoff": self.information_cutoff.isoformat(),
            "assessment": self.assessment_data,
            "news": self.news.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "limitations": list(self.limitations),
        }


class SupportedClaim(ReviewModel):
    statement: Nonblank
    evidence_ids: tuple[Nonblank, ...] = Field(min_length=1)
    rationale: Nonblank


class PerspectiveArgument(SupportedClaim):
    argument_id: Nonblank = Field(description="Unique within this perspective's arguments.")
    credit_implication: Nonblank
    assumptions: tuple[Nonblank, ...] = ()


class PerspectiveAssessment(ReviewModel):
    thesis: Nonblank
    arguments: tuple[PerspectiveArgument, ...]
    counterevidence: tuple[SupportedClaim, ...] = ()
    assumptions: tuple[Nonblank, ...] = ()
    gaps: tuple[Nonblank, ...] = ()
    change_of_view_conditions: tuple[Nonblank, ...] = ()
    confidence: EvidenceConfidence
    confidence_explanation: Nonblank

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        identifiers = [argument.argument_id for argument in self.arguments]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Argument identifiers must be unique within a perspective.")
        if not self.arguments and (not self.gaps or self.confidence != "low"):
            raise ValueError(
                "An unsupported perspective must explain its gaps with low confidence."
            )
        return self


class ArgumentJudgment(ReviewModel):
    perspective: Perspective
    argument_id: Nonblank
    disposition: Literal["accept", "qualify", "reject"]
    rationale: Nonblank
    evidence_ids: tuple[Nonblank, ...] = Field(min_length=1)


class CreditRecommendation(ReviewModel):
    action: ReviewAction
    rationale: Nonblank
    argument_judgments: tuple[ArgumentJudgment, ...] = ()
    evidence_ids: tuple[Nonblank, ...] = ()
    conditions: tuple[Nonblank, ...] = ()
    diligence_questions: tuple[Nonblank, ...] = ()
    unresolved_uncertainties: tuple[Nonblank, ...] = ()
    confidence: EvidenceConfidence
    confidence_explanation: Nonblank


class ReviewExecution(ReviewModel):
    execution_id: str = Field(default_factory=new_identifier)
    role: ReviewRole
    status: Literal["complete", "failed", "skipped"]
    model: str
    prompt_version: str
    elapsed_seconds: float = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    response_id: str | None = None
    error_code: str | None = None


class PerspectiveResult(ReviewModel):
    perspective: Perspective
    analysis: PerspectiveAssessment | None = None
    execution: ReviewExecution


class CreditReviewResult(ReviewModel):
    review_id: str
    created_at: datetime = Field(default_factory=utc_now)
    snapshot: ReviewSnapshot
    decision_context: ExposureDecisionContext | None
    bullish: PerspectiveResult
    bearish: PerspectiveResult
    recommendation: CreditRecommendation
    recommendation_execution: ReviewExecution
    status: Literal["complete", "incomplete", "blocked"]
    issues: tuple[str, ...] = ()


class CreditReviewEvent(ReviewModel):
    review_id: str
    assessment_run_id: str
    kind: Literal["stage_start", "stage_complete", "stage_failed", "review_complete"]
    stage: Literal["news", "bullish", "bearish", "recommendation", "review"]
    error_code: str | None = None
