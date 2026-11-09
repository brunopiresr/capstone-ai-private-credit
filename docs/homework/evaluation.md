# Evaluation

Use separate checks for application behavior, public extraction quality, and live
answer quality. Passing one does not establish the others.

## Offline checks

```bash
make test-all   # App and homework behavior; live scenarios skip
make lint
make test-ml    # Synthetic training and artifact loading
```

These cover formulas, structured verification, controlled extraction/retrieval,
agent workflows, and selected notebook cells. Optional local-cache tests skip when
their ignored sources are absent. Models are scripted or mocked.

## Public-source extraction

```bash
uv run --locked python scripts/compare_public_sec_gold.py \
  --database data/evaluation/snapshots/sec/covenants.sqlite3 \
  --output /tmp/public-sec-comparison --require-complete-sources
```

The runner reads an existing database without changing it. Strict mode also needs
local source Markdown. Supported mismatches, missing core facts, and wholly unevaluable
runs exit nonzero. Unsupported targets are reported separately. See the
[comparison contract](../../tests/evaluation/extraction/README.md) and
[historical findings](../reviews/public_sec_benchmark_triage.md).

## Live answers and reviews

- [60-scenario CSV batch](../../data/evaluation/agent_scenarios/README.md): lesson
  categories, real agent runs, deterministic checks, automated grading, and saved results.
- [Human evaluation app](../../homework/evaluation/README.md): run and rate prepared questions.
- [Agent scenarios](../../homework/agent-tests/README.md): opt-in tool assertions and structured judging.
- [Dated exercise](../../homework/evaluation/2026-10-26/README.md): capture answers, bind labels to hashes, and compare judge results.
- [Credit reviews](../guides/credit_review.md#validation-and-model-evaluation): assess argument support and recommendation quality.

Live generation and judging require credentials and incur provider usage. Keep later
outcome evidence and labels out of generation inputs. Historical scores retain their
dates and are not a current quality guarantee.

## Optional Evidently judges

```bash
uv sync --project homework/llm-judges --group dev --locked
make test-judges
make lint-judges
```

Run this Python 3.13 environment separately from the Python 3.14 project tests.
See [LLM judges](llm_judges.md) for snapshot capture and reports. `make check` runs lint
and app/homework checks; `make check-all` also includes ML and isolated judge checks.
