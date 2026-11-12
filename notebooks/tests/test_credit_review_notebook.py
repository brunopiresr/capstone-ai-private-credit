"""Run notebook 04's cells with real services and offline model boundaries."""

import ast
import asyncio
import inspect
import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import nbformat
import pytest
from model_helpers import ScriptedModel, model_response
from pydantic_ai.messages import ModelRequest, UserPromptPart

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.domain.credit_review import (
    ArgumentJudgment,
    CreditRecommendation,
    PerspectiveArgument,
    PerspectiveAssessment,
    SupportedClaim,
)

NOTEBOOK = Path(__file__).resolve().parents[1] / "04-credit-review.ipynb"


def run_cell(cell, namespace):
    code = compile(cell.source, cell.id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    outcome = eval(code, namespace)
    if inspect.isawaitable(outcome):
        asyncio.run(outcome)


@pytest.fixture
def walkthrough(tmp_path, monkeypatch):
    # Execute the actual setup cell, redirecting output and runtime storage only.
    # Ignore local credentials and observability configuration during offline checks.
    monkeypatch.setattr("credit_monitoring.paths.RUNTIME_DIR", tmp_path)
    monkeypatch.setattr("dotenv.load_dotenv", Mock())
    monkeypatch.setattr("credit_monitoring.observability.configure_observability", Mock())
    monkeypatch.setattr("credit_monitoring.observability.logging.configure_logging", Mock())
    displayed = Mock()
    monkeypatch.setattr("IPython.display.display", displayed)
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    namespace = {}
    for cell in notebook.cells:
        if cell.id == "run-credit-review":
            break
        if cell.cell_type == "code":
            run_cell(cell, namespace)
    return notebook, namespace, displayed


def perspective_response(role):
    return model_response(
        extraction=PerspectiveAssessment(
            thesis=f"Offline {role} thesis.",
            arguments=(
                PerspectiveArgument(
                    argument_id="A1",
                    statement=f"Offline {role} argument.",
                    evidence_ids=("assessment",),
                    rationale="Interpret the supplied assessment without recalculation.",
                    credit_implication="Consider the supplied exposure criteria.",
                    assumptions=("Applied terms remain applicable.",),
                ),
            ),
            counterevidence=(
                SupportedClaim(
                    statement="Source availability is uncertain.",
                    rationale="Reporting dates do not establish availability.",
                    evidence_ids=("assessment",),
                ),
            ),
            assumptions=("No additional verified evidence was supplied.",),
            gaps=("Public news was not retrieved.",),
            change_of_view_conditions=("New verified inputs change the evidence.",),
            confidence="medium",
            confidence_explanation="The supplied result has evidence limitations.",
        )
    )


def recommendation_response(*, messages, info):
    payload = json.loads(
        next(
            part.content
            for message in reversed(messages)
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
    )
    return model_response(
        extraction=CreditRecommendation(
            action="review" if "review" in payload["allowed_actions"] else "defer",
            rationale="Resolve remaining uncertainty before deciding exposure.",
            argument_judgments=tuple(
                ArgumentJudgment(
                    perspective=perspective["perspective"],
                    argument_id=argument["argument_id"],
                    disposition="qualify",
                    rationale="Evidence limitations qualify this argument.",
                    evidence_ids=tuple(argument["evidence_ids"]),
                )
                for perspective in payload["perspectives"]
                if perspective["analysis"] is not None
                for argument in perspective["analysis"]["arguments"]
            ),
            evidence_ids=("assessment",),
            conditions=("Reconcile source availability.",),
            diligence_questions=("When were the sources available?",),
            unresolved_uncertainties=("News is unavailable.",),
            confidence="low",
            confidence_explanation="Material evidence gaps remain.",
        )
    )


def test_review_notebook_schema_syntax_and_empty_outputs():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            assert cell.execution_count is None
            assert cell.outputs == []


def test_review_notebook_calculates_verified_results_without_ml(walkthrough, tmp_path):
    _, namespace, _ = walkthrough
    assessment = namespace["assessment"]
    assert assessment.borrower_id == "SYN002"
    assert assessment.period_end == assessment.information_cutoff == date(2025, 9, 30)
    assert assessment.verification.is_valid
    assert assessment.ml_status == "disabled" and assessment.prediction is None
    assert assessment.results and assessment.history and assessment.trends.covenants
    result = assessment.results[0]
    assert result.compliance_status == "compliant"
    assert result.actual_value == pytest.approx(5.1923076923076925)
    assert result.threshold == 5.5
    assert result.headroom == pytest.approx(0.3076923076923075)
    assert namespace["assessment_service"].settings.ml_enabled is False
    assert namespace["financial_db"].is_relative_to(tmp_path)
    assert namespace["financial_db"].exists()
    assert (namespace["review_dir"] / "analytics.sqlite3").exists()
    assert namespace["review_service"].bullish_agent.model == DEFAULT_MODEL


@pytest.mark.parametrize("scenario", ["complete", "reviewer_failed", "both_failed", "blocked"])
def test_review_notebook_runs_and_displays_successes_and_failures(walkthrough, capsys, scenario):
    notebook, namespace, displayed = walkthrough
    service = namespace["review_service"]
    models = [
        ScriptedModel(response=perspective_response("bullish")),
        ScriptedModel(response=perspective_response("bearish")),
        ScriptedModel(),
    ]
    models[2].respond.side_effect = recommendation_response
    service.bullish_agent.model, service.bearish_agent.model, service.recommendation_agent.model = (
        models
    )
    if scenario in {"reviewer_failed", "both_failed"}:
        models[0].respond.side_effect = RuntimeError("Offline provider failure")
    if scenario == "both_failed":
        models[1].respond.side_effect = RuntimeError("Offline provider failure")
    if scenario == "blocked":
        namespace["assessment"].verification.add("error", "test", "results", "Invalid inputs.")
    original = namespace["assessment"].model_dump_json()
    for cell in notebook.cells:
        if cell.cell_type == "code" and cell.id in {
            "run-credit-review",
            "display-review-perspectives",
            "display-credit-recommendation",
            "display-review-evidence",
            "display-review-execution",
        }:
            run_cell(cell, namespace)

    review = namespace["review"]
    assert namespace["assessment"].model_dump_json() == original
    assert review.snapshot.assessment_run_id == namespace["assessment"].assessment_run_id
    assert review.snapshot.news.status == "unavailable"
    assert review.snapshot.assessment_data["ml_status"] == "disabled"
    assert review.snapshot.assessment_data["prediction"] is None
    for reference in review.snapshot.evidence:
        assert namespace["inspect_evidence"](reference.evidence_id) is not None
    assert displayed.called
    output = capsys.readouterr().out
    assert "Assessment run:" in output and "Selected evidence:" in output
    if scenario == "complete":
        assert review.status == "complete" and review.recommendation.action == "review"
        assert len(review.recommendation.argument_judgments) == 2
        assert all(model.respond.call_count == 1 for model in models)
        rendered = "\n".join(
            str(getattr(call.args[0], "data", call.args[0])) for call in displayed.call_args_list
        )
        for text in (
            "Offline bullish thesis.", "Offline bearish thesis.", "Counterevidence",
            "Perspective assumptions", "Evidence gaps", "What would change this view",
            "Conditions", "Diligence questions", "Unresolved uncertainties",
        ):
            assert text in rendered
        # A new review must reuse the selected calculation, not create another run.
        run_cell(next(cell for cell in notebook.cells if cell.id == "run-credit-review"), namespace)
        assert namespace["review"].review_id != review.review_id
        assert namespace["review"].snapshot.assessment_run_id == review.snapshot.assessment_run_id
    elif scenario == "blocked":
        assert review.status == "blocked" and review.recommendation.action == "defer"
        assert all(not model.respond.called for model in models)
        assert "Analysis unavailable: verification_failed" in output
    else:
        assert review.status == "incomplete" and review.recommendation.action == "defer"
        assert review.bullish.analysis is None
        assert (review.bearish.analysis is None) == (scenario == "both_failed")
        assert "Analysis unavailable: model_error" in output
        assert models[2].respond.called == (scenario == "reviewer_failed")
