# Homework agent tests

The three [main scenarios](test-cases/three-main-cases.md) share prompts, exact tool contracts and answer criteria in `scenarios.py`:

- `test_main_scenarios.py` uses ordinary assertions for tool calls, dates, and structured results.
- `test_llm_scenarios.py` runs the same scenarios asynchronously, checks the same tool contracts first, and calls `await assert_criteria(response, [...])` to check the response and tool behavior.

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

Both flags enable live requests and are aliases. Credentials are loaded from `OPENAI_API_KEY` or the repository's `.env`. Use `--homework-model` to change the generating model; the judge uses the model specified in `create_judge_agent()`. Both suites use real local services and temporary databases. Without a live flag, the six live scenarios skip while offline helper regressions run:

```bash
uv run pytest homework-tests -q
```

The judge tests run directly in the project environment. `test_criteria_helpers.py`
retains offline checks of valid and invalid criteria, incomplete runs, failed criteria,
missing/duplicate/reordered/mismatched feedback, failed-judgment artifact capture, and
answer/ordered-trace preservation. These checks explicitly disable real model requests.
Default root pytest discovery includes this directory; `make test-homework` runs it alone.
Both live suites retain answer, generating-model identity, ordered tool arguments and
results in ignored `data/processed/judges-homework-*` directories. The judged suite
also saves judge identity, criteria and feedback before asserting acceptance.

Validation on October 18, 2026 initially reproduced all six live failures. The
assessment prompt now requires both analyst-supplied dates before any tool call,
an initial financial read, and the exact assessment or forecast sequence. Tool
instructions reinforce the forecast prerequisite. The same six scenarios then
passed, including all three final-answer judge checks. A later run exposed an
omitted activation comparison; the prompt now asks for the observed input and
trigger threshold. Final validation after the streaming refactor: **14 passed**
(eight offline helper checks plus all six live scenarios), using `openai-responses:gpt-4o-mini`
for generation and `openai:gpt-4o-mini` for judging. These are observed live results, not expected-failure
markers or proof of general model reliability. Subsequent runs may still fail and
retain their captures for diagnosis.


Offline discovery and lint (no live flag or credentials required):

```bash
uv run --locked pytest homework-tests --collect-only -q
make test-homework
make lint
```

The historical live results above have not been rerun by the F13–F19 cleanup. Current
mocked helper checks validate plumbing, not answer quality or judge calibration. The
optional Evidently suite uses its own Python 3.13 environment; see [evaluation](../docs/evaluation.md).
