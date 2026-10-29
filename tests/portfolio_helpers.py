"""Controlled portfolio inputs and a scripted boundary for the three real review agents."""

import json
import shutil
from pathlib import Path

from model_helpers import ScriptedModel, model_response
from pydantic_ai.messages import ModelRequest, UserPromptPart

from credit_monitoring.domain.credit_review import (
    ArgumentJudgment,
    CreditRecommendation,
    PerspectiveArgument,
    PerspectiveAssessment,
)

ROOT = Path(__file__).resolve().parents[1]


def portfolio_inputs(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    target = data_root / "app" / "synthetic"
    target.mkdir(parents=True)
    for filename in (
        "synthetic_borrowers.csv",
        "synthetic_covenant_terms.csv",
        "financials.sqlite3",
    ):
        shutil.copyfile(ROOT / "data" / "app" / "synthetic" / filename, target / filename)
    return data_root


def review_model() -> ScriptedModel:
    model = ScriptedModel(model_name="portfolio-offline")

    def respond(messages, info):
        payload = json.loads(
            next(
                part.content
                for message in reversed(messages)
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, UserPromptPart)
            )
        )
        if "perspectives" in payload:
            output = CreditRecommendation(
                action="review" if "review" in payload["allowed_actions"] else "defer",
                rationale="The supplied arguments support an evidence-limited review.",
                argument_judgments=tuple(
                    ArgumentJudgment(
                        perspective=item["perspective"],
                        argument_id=argument["argument_id"],
                        disposition="qualify",
                        rationale="Evidence limitations remain material.",
                        evidence_ids=("assessment",),
                    )
                    for item in payload["perspectives"]
                    if item["analysis"]
                    for argument in item["analysis"]["arguments"]
                ),
                evidence_ids=("assessment",),
                confidence="medium",
                confidence_explanation="Scripted output over the real saved assessment.",
            )
        else:
            output = PerspectiveAssessment(
                thesis="Evaluate the saved covenant result against the decision criteria.",
                arguments=(
                    PerspectiveArgument(
                        argument_id="A1",
                        statement="The saved assessment supplies the compliance result.",
                        evidence_ids=("assessment",),
                        rationale="The result is read without recalculation.",
                        credit_implication="Review the existing exposure with the remaining gaps.",
                    ),
                ),
                gaps=("Source availability dates remain uncertain.",),
                confidence="medium",
                confidence_explanation="Deterministic evidence with explicit limitations.",
            )
        return model_response(extraction=output)

    model.respond.side_effect = respond
    return model
