# Homework and experiments

Exercises use the shared [application services](../src/credit_monitoring).
Start with the [project setup](../README.md#run-web-v2).

For guided platform testing, use the top-level [notebooks](../notebooks).
The [reviewer quick start](../README.md#try-the-notebooks) covers
setup, example questions, and the recommended notebook sequence.

| Exercise | Purpose | Environment |
| --- | --- | --- |
| [Monitoring](monitoring/README.md) | Chat, agent activity, and optional Logfire telemetry | Project environment |
| [Agent tests](agent-tests/README.md) | Three scenarios with tool assertions and answer judging | Project; live requests opt in |
| [Evaluation](evaluation/README.md) | Human ratings and a dated evaluation runner | Project; answer generation needs credentials |
| [LLM judges](../docs/evaluation/llm-judges.md) | Optional Evidently evaluation of captured outputs | Separate Python 3.13 environment |

```bash
make test-homework  # Offline exercises; live scenarios skip
make test-all       # App, notebook, and homework checks
```

[Data layout](../data/README.md) separates source inputs, expected answers, and ignored
local output. Recorded live results are historical measurements; offline checks do not
reproduce their quality scores.
