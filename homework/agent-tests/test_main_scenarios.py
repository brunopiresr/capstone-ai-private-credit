"""Live tool-contract checks; final-answer meaning is evaluated in the judged suite."""

import pytest
from scenarios import SCENARIOS, capture_answer, check_scenario


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_tool_contract(credit_agent, scenario_artifacts, scenario):
    answer = credit_agent.ask(scenario.query, borrower_id=scenario.borrower_id)
    capture_answer(scenario_artifacts, scenario, answer, credit_agent.model)
    check_scenario(scenario, answer)
