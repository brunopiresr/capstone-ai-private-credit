# Evaluate the POC

A reviewer needs to distinguish software behavior, extraction quality, generated
answer quality, and the judge's own reliability. Passing one does not establish
the others. Start with [saved results](results.md) to inspect evidence without
API spending. The README ends with a [self-evaluation](../../README.md#self-evaluation).

## Offline behavior

After [setup](../guides/setup.md):

```bash
make test-all
make lint
make test-ml
```

The suites cover calculations, structured verification, controlled retrieval and
extraction, agent workflows, V2, selected notebook cells, and coursework helpers.
Models are scripted or mocked; opt-in live cases skip. Local-cache tests may also
skip when ignored sources are absent. `make test-ml` covers synthetic training and
artifact loading. These are behavior checks rather than live accuracy measurements.

[CI](../../.github/workflows/ci.yml) runs locked Python 3.14 app/homework checks and
separate Python 3.13 judge checks without API keys.

## Agent answer quality

The [60-scenario suite](../../data/evaluation/agent_scenarios/README.md) is the main
diagnostic agent example. It retains requests, answers, actual tools, deterministic
checks, judge packets, and manifests. It is not a held-out or human-calibrated test.

```bash
uv run --locked python -m credit_monitoring.evaluation.agent_batch validate
```

That validates cases without live generation. To capture a small new run:

```bash
uv run --locked python -m credit_monitoring.evaluation.agent_batch run \
  --cases H01,H16,O01 --output data/runtime/evaluation/new-run --env-file .env
```

This makes paid generation and judge requests. Use a new output directory. Add
`--skip-judge` to omit semantic grading, leaving that dimension unavailable. Check
the saved summary: successful execution or process exit is not itself a quality pass.
Do not compare scores from changed cases, source packets, graders, or prompts as
a controlled improvement experiment.

Other retained tools have distinct purposes:

| Tool | Purpose and limitation |
| --- | --- |
| [50-case exercise](../../evaluations/README.md) | Heuristic response labeling and judge agreement; labels are not independently verified ground truth. |
| [Human rating app](../../homework/evaluation/README.md) | Run and rate prepared questions; app availability does not establish completed human evaluation. |
| [27-case workbench](../../homework/evaluation/2026-10-26/README.md) | Dated answer capture and judge comparison; previously exposed holdouts are not unseen cases. |
| [Agent scenarios](../../homework/agent-tests/README.md) | Opt-in tool assertions and structured judging. |
| [Credit-review checks](../guides/agents.md#validation-and-model-evaluation) | Review argument support, counterevidence, action appropriateness, and follow-up questions. |

Generation must not see evaluator-only references, labels, later outcomes, or
benchmark notes. Capture the evidence actually used, rather than rerunning search
afterward. Keep incomplete runs and missing grades visible.

## Public-source extraction

```bash
uv run --locked python scripts/compare_public_sec_gold.py \
  --database data/evaluation/snapshots/sec/covenants.sqlite3 \
  --output /tmp/public-sec-comparison
```

The runner opens the historical database read-only. Strict
`--require-complete-sources` additionally needs the corresponding local Markdown;
it is not a fresh-checkout no-download guarantee. Supported mismatches, missing
core facts, and wholly unevaluable runs exit nonzero. Unsupported assessment
targets are reported separately. Read the [comparison contract](../../tests/evaluation/extraction/README.md)
and [historical result](results.md#public-source-extraction).

## Optional LLM judges

```bash
uv sync --project homework/llm-judges --group dev --locked
make test-judges
make lint-judges
uv run --locked python scripts/run_evaluation.py \
  --input data/evaluation/judges/demo_cases.jsonl --dry-run
```

Evidently uses an isolated Python 3.13 environment. The dry run checks nine authored
demo records without generation. See [LLM judges](llm-judges.md) for paid execution,
snapshot fields, quality gates, and metric interpretation. `make check-all` includes
app, ML, and isolated judge checks.
