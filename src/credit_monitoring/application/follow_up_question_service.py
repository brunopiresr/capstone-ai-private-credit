"""Bind generated questions and chat context to immutable assessment/review inputs."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from credit_monitoring.agents.follow_up_questions import (
    PROMPT_VERSION,
    FollowUpQuestionAgent,
    FollowUpQuestions,
    validate_questions,
)
from credit_monitoring.agents.models import model_identity
from credit_monitoring.application.review_evidence import _sanitize
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult

MAX_CONTEXT_CHARS = 240_000


def analysis_context(assessment: RiskAssessment, review: CreditReviewResult | None) -> dict:
    """Keep source facts and saved agent interpretations explicitly separate."""
    if review is not None and (
        review.snapshot.assessment_run_id != assessment.assessment_run_id
        or review.snapshot.borrower_id != assessment.borrower_id
        or review.snapshot.period_end != assessment.period_end
        or review.snapshot.information_cutoff != assessment.information_cutoff
    ):
        raise ValueError("The saved credit review does not match this assessment.")
    context = {
        "assessment": _sanitize(assessment),
        "review": review.model_dump(mode="json", exclude={"snapshot"}) if review else None,
        "review_evidence": {
            "evidence": [e.model_dump(mode="json") for e in review.snapshot.evidence],
            "news": review.snapshot.news.model_dump(mode="json"),
            "limitations": list(review.snapshot.limitations),
            "review_information_cutoff": (
                review.snapshot.review_information_cutoff or review.snapshot.information_cutoff
            ).isoformat(),
            "additional_context": json.loads(review.snapshot.additional_context_json),
        }
        if review
        else None,
    }
    if len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_CHARS:
        raise ValueError("This analysis exceeds the follow-up context limit.")
    return context


class SavedFollowUps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    context_hash: str
    model: str
    prompt_version: str
    output: FollowUpQuestions
    usage: dict[str, int] = Field(default_factory=dict)


class FollowUpQuestionService:
    def __init__(self, working_dir: Path, agent: FollowUpQuestionAgent):
        self.directory = Path(working_dir) / "follow_up_questions"
        self.agent = agent

    def _identity(self, context: dict) -> tuple[str, Path]:
        digest = hashlib.sha256(
            json.dumps(context, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        key = hashlib.sha256(
            f"{digest}:{model_identity(self.agent.model)}:{PROMPT_VERSION}".encode()
        ).hexdigest()
        return digest, self.directory / f"{key}.json"

    def load(
        self, assessment: RiskAssessment, review: CreditReviewResult | None
    ) -> SavedFollowUps | None:
        context = analysis_context(assessment, review)
        digest, path = self._identity(context)
        try:
            if path.stat().st_size > 32_000:
                return None
            saved = SavedFollowUps.model_validate_json(path.read_text())
            if (
                saved.version != 1
                or saved.context_hash != digest
                or saved.model != model_identity(self.agent.model)
                or saved.prompt_version != PROMPT_VERSION
            ):
                return None
            validate_questions(saved.output, context)
            return saved
        except OSError, ValidationError, ValueError:
            return None

    def generate(
        self,
        assessment: RiskAssessment,
        review: CreditReviewResult | None,
        *,
        regenerate: bool = False,
    ) -> SavedFollowUps:
        if not regenerate and (saved := self.load(assessment, review)) is not None:
            return saved
        context = analysis_context(assessment, review)
        output, usage = self.agent.generate(context)
        validate_questions(output, context)
        digest, path = self._identity(context)
        saved = SavedFollowUps(
            context_hash=digest,
            model=model_identity(self.agent.model),
            prompt_version=PROMPT_VERSION,
            output=output,
            usage=usage,
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as file:
                temporary = Path(file.name)
                file.write(saved.model_dump_json())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return saved
