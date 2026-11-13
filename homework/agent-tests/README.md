# Agent tests

Three [main scenarios](test-cases/three-main-cases.md) cover missing financial inputs,
missing dates, and an unavailable stub forecast. Shared prompts and criteria live in
`scenarios.py`; the [scenario catalog](test-cases/all-scenarios.md) provides manual extensions.

| Suite | Checks |
| --- | --- |
| `test_main_scenarios.py` | Actual tool calls, dates, and structured results |
| `test_llm_scenarios.py` | The same tool contract, followed by a structured final-answer judge |
| `test_criteria_helpers.py` | Offline validation, failure capture, and ordered trace handling |

Run offline checks:

```bash
uv run --locked pytest homework/agent-tests -q
```

Live tests require `OPENAI_API_KEY` in the environment or root `.env` and incur usage:

```bash
uv run --locked pytest homework/agent-tests/test_main_scenarios.py --run-live -v -s
uv run --locked pytest homework/agent-tests/test_llm_scenarios.py --run-llm-evals -v -s
```

The two live flags are aliases; without either, six live scenarios skip. Use
`--homework-model` to change generation. The judge uses `openai:gpt-4o-mini` as configured
in `create_judge_agent()` and evaluates all criteria in one request per scenario.
It receives the completed answer and actual ordered tool trace after generation.

Live captures save model identities, answers, tool results, criteria, and feedback under
ignored `data/runtime/judges-homework-*`. Failed judgments are saved before assertions.

The recorded streaming-refactor run passed eight helper checks and six live scenarios.
This historical result is not a current reliability claim; later runs may fail.
`make test-homework` includes offline helpers. See [evaluation](../../docs/evaluation/README.md)
for the separate Evidently environment and other measurement options.
