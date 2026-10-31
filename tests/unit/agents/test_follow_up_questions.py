"""Real question agent and sidecar storage with controlled model responses."""

import json
from datetime import date
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel, model_response
from portfolio_helpers import portfolio_inputs, review_model
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, UserPromptPart

from credit_monitoring.agents.follow_up_questions import (
    FollowUpQuestion,
    FollowUpQuestionAgent,
    FollowUpQuestions,
    validate_questions,
)
from credit_monitoring.application.bootstrap import create_portfolio_service
from credit_monitoring.application.follow_up_question_service import (
    FollowUpQuestionService,
    analysis_context,
)
from credit_monitoring.domain.credit_review import ExposureDecisionContext


def question_output(context, *, question="What evidence supports the recommendation?"):
    review = context["review"]
    return FollowUpQuestions(
        assessment_run_id=context["assessment"]["assessment_run_id"],
        review_id=review["review_id"] if review else None,
        questions=[
            FollowUpQuestion(
                question=question,
                reason="Investigate the saved decision and its evidence limitations.",
                references=["/review/recommendation/rationale"]
                if review
                else ["/assessment/verification"],
            )
        ],
    )


def payload(messages):
    return json.loads(
        next(
            p.content
            for m in reversed(messages)
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, UserPromptPart)
        )
    )


@pytest.fixture
def analysis(tmp_path):
    service = create_portfolio_service(
        data_root=portfolio_inputs(tmp_path), working_dir=tmp_path / "working", model=review_model()
    )
    assessment = service.assess(["SYN002"], period_end=date(2025, 9, 30), cutoff=date(2025, 9, 30))[
        0
    ].assessment
    review = service.review(
        assessment.assessment_run_id,
        ExposureDecisionContext(
            question="Review the exposure.", credit_criteria=("Consider evidence gaps.",)
        ),
    )
    return service, assessment, review


def test_generator_gets_calculations_and_all_risk_agents_and_cache_survives_reload(analysis):
    portfolio, assessment, review = analysis
    model = ScriptedModel()
    seen = []

    def respond(messages, info):
        data = payload(messages)
        seen.append(data)
        assert not info.function_tools  # Generation has no execution tools.
        return model_response(extraction=question_output(data))

    model.respond.side_effect = respond
    service = FollowUpQuestionService(
        portfolio.repository.database_path.parent, FollowUpQuestionAgent(model)
    )
    original = portfolio.repository.get_assessment(assessment.assessment_run_id).model_dump_json()
    first = service.generate(assessment, review)
    assert model.respond.call_count == 1
    assert seen[0]["assessment"]["results"][0]["actual_value"] == assessment.results[0].actual_value
    assert seen[0]["review"]["bullish"]["analysis"] == review.bullish.analysis.model_dump(
        mode="json"
    )
    assert seen[0]["review"]["bearish"]["analysis"] == review.bearish.analysis.model_dump(
        mode="json"
    )
    assert seen[0]["review"]["recommendation"]["rationale"] == review.recommendation.rationale
    assert seen[0]["review_evidence"]["evidence"]
    assert "narrative" not in seen[0]["assessment"]
    assert first.usage["requests"] == 1
    reloaded = FollowUpQuestionService(service.directory.parent, FollowUpQuestionAgent(model))
    assert reloaded.load(assessment, review) == first
    assert reloaded.generate(assessment, review) == first
    assert model.respond.call_count == 1
    reloaded.generate(assessment, review, regenerate=True)
    assert model.respond.call_count == 2
    assert (
        portfolio.repository.get_assessment(assessment.assessment_run_id).model_dump_json()
        == original
    )


def test_new_risk_conclusions_change_generation_context_even_with_same_calculations(analysis):
    _, assessment, review = analysis
    changed = review.model_copy(
        update={
            "recommendation": review.recommendation.model_copy(
                update={"rationale": "New recommendation depends on reconciling debt."}
            )
        }
    )
    original = analysis_context(assessment, review)
    revised = analysis_context(assessment, changed)
    assert original["assessment"] == revised["assessment"]
    assert original != revised


def test_cache_invalidates_for_review_calculations_model_and_prompt(analysis, monkeypatch):
    portfolio, assessment, review = analysis
    service = portfolio.follow_up_service
    assert service.load(assessment, review)
    assert service.load(assessment, None) is None
    changed_review = review.model_copy(update={"review_id": "new-review"})
    assert service.load(assessment, changed_review) is None
    changed_inputs = assessment.model_copy(update={"issues": ["New availability limitation."]})
    assert service.load(changed_inputs, review) is None
    monkeypatch.setattr(
        "credit_monitoring.application.follow_up_question_service.PROMPT_VERSION", "v2"
    )
    assert service.load(assessment, review) is None


@pytest.mark.parametrize(
    "pointer",
    [
        "/review/not_a_finding",
        "/assessment/results/999",
        "/assessment/results/-1",
        "/other",
        "/review/bullish/analysis/bogus",
    ],
)
def test_unknown_references_are_rejected(analysis, pointer):
    _, assessment, review = analysis
    context = analysis_context(assessment, review)
    output = question_output(context)
    invalid = output.model_copy(
        update={"questions": [output.questions[0].model_copy(update={"references": [pointer]})]}
    )
    with pytest.raises(ValueError, match="reference|Reference"):
        validate_questions(invalid, context)


def test_output_rejects_duplicates_empty_text_and_more_than_three(analysis):
    _, assessment, review = analysis
    data = question_output(analysis_context(assessment, review)).model_dump()
    for questions in (
        [data["questions"][0]] * 2,
        [data["questions"][0]] * 4,
        [{**data["questions"][0], "question": "  "}],
    ):
        with pytest.raises(ValidationError):
            FollowUpQuestions.model_validate({**data, "questions": questions})
    with pytest.raises(ValueError, match="match"):
        validate_questions(
            FollowUpQuestions.model_validate({**data, "review_id": "other"}),
            analysis_context(assessment, review),
        )


def test_failed_regeneration_retains_saved_questions_and_analysis(analysis, monkeypatch):
    portfolio, assessment, review = analysis
    old = portfolio.follow_up_service.load(assessment, review)
    monkeypatch.setattr(
        portfolio.follow_up_service.agent, "generate", Mock(side_effect=RuntimeError())
    )
    with pytest.raises(RuntimeError):
        portfolio.follow_up_service.generate(assessment, review, regenerate=True)
    assert portfolio.follow_up_service.load(assessment, review) == old
    portfolio.follow_up_service.directory.joinpath(
        portfolio.follow_up_service._identity(analysis_context(assessment, review))[1].name
    ).write_text("broken cache")
    assert portfolio.follow_up_service.load(assessment, review) is None
    portfolio.generate_follow_ups(assessment, review)
    assert review.review_id in portfolio.follow_up_errors
    assert portfolio.repository.latest_review(assessment.assessment_run_id) == review


def test_no_review_and_incomplete_review_and_wrong_scope(analysis):
    portfolio, assessment, review = analysis
    saved = portfolio.follow_up_service.generate(assessment, None)
    assert saved.output.review_id is None
    incomplete = review.model_copy(
        update={"status": "incomplete", "issues": ("Bearish stage failed.",)}
    )
    context = analysis_context(assessment, incomplete)
    assert context["review"]["status"] == "incomplete"
    assert context["review"]["issues"] == ["Bearish stage failed."]
    wrong = review.model_copy(
        update={"snapshot": review.snapshot.model_copy(update={"assessment_run_id": "other"})}
    )
    with pytest.raises(ValueError, match="match"):
        analysis_context(assessment, wrong)


def test_model_failure_or_invalid_output_does_not_produce_fallback(analysis):
    _, assessment, review = analysis
    context = analysis_context(assessment, review)
    model = ScriptedModel(
        response=model_response(status="incomplete", extraction=question_output(context))
    )
    with pytest.raises(Exception):
        FollowUpQuestionAgent(model).generate(context)
    invalid = question_output(context).model_copy(update={"assessment_run_id": "wrong"})
    model = ScriptedModel(response=model_response(extraction=invalid))
    with pytest.raises(Exception):
        FollowUpQuestionAgent(model).generate(context)
    assert model.respond.call_count == 2  # One bounded validation retry, no fallback.
