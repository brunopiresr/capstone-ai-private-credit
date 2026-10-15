# Homework agent tests

The three [main scenarios](../homework-test/three-main-cases.md) have two separate test files:

- `test_main_scenarios.py` uses ordinary assertions for tool calls, dates, and structured results.
- `test_llm_scenarios.py` runs the same scenarios asynchronously and calls `await assert_criteria(response, [...])` to check the response and tool behavior.

`criteria_helpers.py` uses a PydanticAI judge (`openai:gpt-4o-mini`) with structured `JudgeFeedback`. One judge call evaluates all criteria for a completed scenario. The helper prints the feedback and asserts that every criterion passed. Incomplete agent runs and missing, reordered, or mismatched feedback fail explicitly. Evidence comes from the actual answer and ordered `AgentAnswer.tool_trace`, including tool arguments and returned results.

The LLM tests check missing financial inputs and FCCR activation for SYN010, missing-date clarification for SYN002, and an unavailable stub forecast distinguished from current compliance and headroom. Tool-order and exact date requirements are included in the criteria. The judge receives these expectations only after the agent runs.

Run the ordinary assertions:

```bash
uv run pytest homework-tests/test_main_scenarios.py --run-live -v -s
```

Run the async judge tests:

```bash
uv run pytest homework-tests/test_llm_scenarios.py --run-llm-evals -v -s
```

Both flags enable live requests and are aliases. Credentials are loaded from `OPENAI_API_KEY` or the repository's `.env`. Use `--homework-model` to change the generating model; the judge uses the model specified in `create_judge_agent()`. Both suites use real local services and temporary databases. Without a live flag, all six tests are skipped:

```bash
uv run pytest homework-tests -q
```

The judge tests run directly in the project's Python environment. They use no evaluation script, Evidently integration, separate environment, report generation, or artifact directories. The ordinary tests retain their existing answer captures. Judge explanations and live failures should be reviewed; production agent behavior is unchanged.

Validation on October 15, 2026: **110 existing offline tests passed**, all six homework scenarios skipped without a live flag, and **seven mocked helper checks passed** (including failed criteria, missing/reordered/mismatched feedback, trace preservation, and incomplete runs). Ruff checks passed.

The two live suites ran separately with the default generating model:

| Suite | Result | Observed failures |
| --- | --- | --- |
| Ordinary assertions | 0 passed, 3 failed | Assessment and forecast calls omitted the initial financial read; the missing-dates case guessed dates and reached the tool-round limit. |
| Async LLM judge | 0 passed, 3 failed | The judge rejected missing/incorrect prerequisite tool order in the assessment and forecast cases; the missing-dates run reached the tool-round limit and failed before judging. |

The failing expectations remain active. These are observations of the current agent, not expected-failure markers or fixes to its behavior.
