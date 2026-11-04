# Homework and experiments

Exercises use the shared [application services](../src/credit_monitoring/).
Start with the [project setup](../README.md#run-the-app).

| Exercise | Purpose | Environment |
| --- | --- | --- |
| [Notebooks](notebooks/) | Run `01-setup`, `02-rag`, then `03-agents` | Project Python 3.14 kernel |
| [Monitoring](monitoring/README.md) | Chat, agent activity, and optional Logfire telemetry | Project environment |
| [Agent tests](agent-tests/README.md) | Three scenarios with tool assertions and answer judging | Project; live requests opt in |
| [Evaluation](evaluation/README.md) | Human ratings and a dated evaluation runner | Project; answer generation needs credentials |
| [LLM judges](../docs/homework/llm_judges.md) | Optional Evidently evaluation of captured outputs | Separate Python 3.13 environment |

For Jupyter, run `uv sync --group notebooks --group dev --extra ml --locked` and select
the project's `.venv` kernel. Model cells need `OPENAI_API_KEY`; uncached SEC downloads
also need `SEC_USER_AGENT`.

```bash
make test-homework  # Offline exercises; live scenarios skip
make test-all       # App and homework checks
```

[Data layout](../data/README.md) separates source inputs, expected answers, and ignored
local output. Recorded live results are historical measurements; offline checks do not
reproduce their quality scores.
