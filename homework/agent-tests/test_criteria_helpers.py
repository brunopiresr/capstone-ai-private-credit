"""Offline judge plumbing checks; mocked feedback does not measure answer quality."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import criteria_helpers as helpers
import pytest
from pydantic_ai import models

from credit_monitoring.domain.agent import AgentAnswer, ToolExecution
from credit_monitoring.domain.tool_results import ToolFailure

CRITERIA = ["Ask for both dates.", "Invent no probability."]


@pytest.fixture
def judge(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    agent = SimpleNamespace(run=AsyncMock())
    monkeypatch.setattr(helpers, "create_judge_agent", lambda: agent)
    return agent


def feedback(criteria=CRITERIA, *, passed=True):
    return helpers.JudgeFeedback(
        criteria=[
            helpers.JudgeCriterion(
                criterion_description=item, passed=passed, judgement="Evidence checked."
            )
            for item in criteria
        ],
        feedback="Controlled feedback.",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "complete,error", [(False, None), (False, "model_error"), (True, "model_error")]
)
async def test_incomplete_or_error_runs_never_reach_judge(judge, complete, error):
    with pytest.raises(AssertionError, match="Agent run failed"):
        await helpers.assert_criteria(AgentAnswer(complete=complete, error=error), CRITERIA)
    judge.run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "criteria", [[], CRITERIA[:1], CRITERIA[::-1], ["Wrong", CRITERIA[1]], [CRITERIA[0]] * 2]
)
async def test_missing_reordered_or_mismatched_feedback_fails(judge, criteria):
    judge.run.return_value = SimpleNamespace(output=feedback(criteria))
    with pytest.raises(AssertionError, match="every supplied criterion"):
        await helpers.assert_criteria(AgentAnswer(answer="Actual answer"), CRITERIA)


@pytest.mark.asyncio
async def test_failed_criterion_is_captured_and_rejected(judge, tmp_path):
    judge.run.return_value = SimpleNamespace(output=feedback(passed=False))
    capture = tmp_path / "judge.json"
    with pytest.raises(AssertionError, match="Ask for both dates"):
        await helpers.assert_criteria(
            AgentAnswer(answer="Invented 20% risk"), CRITERIA, artifact_path=capture
        )
    stored = json.loads(capture.read_text())
    assert stored["judge_model"] == helpers.JUDGE_MODEL
    assert not stored["feedback"]["criteria"][0]["passed"]


@pytest.mark.asyncio
async def test_actual_answer_and_ordered_tool_evidence_reach_judge(judge):
    judge.run.return_value = SimpleNamespace(output=feedback())
    answer = AgentAnswer(
        answer="Supply reporting date and information cutoff.",
        tool_trace=[
            ToolExecution(
                call_id=str(index),
                name=name,
                arguments={"period_end": "2025-09-30"},
                outcome=ToolFailure(code="invalid_arguments", message="Cutoff required"),
            )
            for index, name in enumerate(("get_financials", "assess_covenants"))
        ],
    )
    assert await helpers.assert_criteria(answer, CRITERIA) == feedback()
    prompt = judge.run.await_args.args[0]
    assert answer.answer in prompt
    tool_json = prompt.split("<TOOL_CALLS>\n", 1)[1].split("\n</TOOL_CALLS>", 1)[0]
    calls = json.loads(tool_json)
    assert [call["name"] for call in calls] == ["get_financials", "assess_covenants"]
    assert calls[0]["arguments"] == {"period_end": "2025-09-30"}
    assert calls[0]["outcome"]["message"] == "Cutoff required"


@pytest.mark.asyncio
@pytest.mark.parametrize("criteria", [[], "one criterion", [""], [" \t "]])
async def test_invalid_criteria_never_reach_judge(judge, criteria):
    with pytest.raises(ValueError, match="nonempty sequence"):
        await helpers.assert_criteria(AgentAnswer(), criteria)
    judge.run.assert_not_awaited()
