"""Synthetic provider responses used by the chat and telemetry integration checks."""

import asyncio
import json

from model_helpers import model_response
from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from credit_monitoring.domain.credit_review import (
    ArgumentJudgment,
    CreditRecommendation,
    PerspectiveArgument,
    PerspectiveAssessment,
)

DATES = {"period_end": "2025-09-30", "information_cutoff": "2025-09-30"}
REVIEW_ARGS = {
    "borrower_id": "SYN001",
    **DATES,
    "credit_criteria": ["Assess compliance, headroom and material evidence gaps."],
    "ml_mode": "Stub",
}
QUESTION = (
    "Analyze SYN001 for 2025-09-30 with information cutoff 2025-09-30. "
    "Use Stub ML. My criteria are compliance, headroom and material evidence gaps."
)


def text_response(text="The review is complete; see the cited service results."):
    return ModelResponse(parts=[TextPart(text)], finish_reason="stop")


def review_model():
    async def reply(messages, info):
        await asyncio.sleep(0)
        payload = json.loads(
            next(
                part.content
                for message in reversed(messages)
                for part in message.parts
                if isinstance(part, UserPromptPart)
            )
        )
        if "perspectives" not in payload:
            return model_response(
                extraction=PerspectiveAssessment(
                    thesis="Synthetic evidence-backed perspective.",
                    arguments=(
                        PerspectiveArgument(
                            argument_id="A1",
                            statement="The reported covenant results inform this view.",
                            evidence_ids=("assessment",),
                            rationale="Use supplied calculations.",
                            credit_implication="Weigh compliance against the analyst criteria.",
                        ),
                    ),
                    confidence="medium",
                    confidence_explanation="Synthetic data; availability unknown.",
                )
            )
        return model_response(
            extraction=CreditRecommendation(
                action="review" if "review" in payload["allowed_actions"] else "defer",
                rationale="The supplied perspectives and evidence require analyst review.",
                evidence_ids=("assessment",),
                argument_judgments=tuple(
                    ArgumentJudgment(
                        perspective=perspective["perspective"],
                        argument_id=argument["argument_id"],
                        disposition="qualify",
                        rationale="Retain the supplied evidence gaps.",
                        evidence_ids=("assessment",),
                    )
                    for perspective in payload["perspectives"]
                    if perspective["analysis"]
                    for argument in perspective["analysis"]["arguments"]
                ),
                confidence="low"
                if any(p["analysis"] is None for p in payload["perspectives"])
                else "medium",
                confidence_explanation="Synthetic inputs and source-availability limitations.",
            )
        )

    return FunctionModel(reply, model_name="scripted-review")
