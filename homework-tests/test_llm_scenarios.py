"""Check actual tools and judge the final answer from the same live execution."""

import pytest
from criteria_helpers import assert_criteria
from scenarios import SCENARIOS, capture_answer, check_scenario


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
async def test_analyst_answer(credit_agent, scenario_artifacts, scenario):
    answer = await credit_agent.ask_async(scenario.query, borrower_id=scenario.borrower_id)
    capture_answer(scenario_artifacts, scenario, answer, credit_agent.model)
    check_scenario(scenario, answer)
    await assert_criteria(
        answer, scenario.criteria, artifact_path=scenario_artifacts / "judge-feedback.json"
    )
