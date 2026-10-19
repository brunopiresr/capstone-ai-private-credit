# Evaluation

## Portable offline checks

```bash
make test          # Python 3.14: tests + homework helper regressions; six live scenarios skip.
make lint          # All retained root Python areas, including homework and downloader.
make test-ml       # Explicit ml extra: real synthetic training and artifact loading.
```

The root suite includes deterministic formulas, active verification rejection tests,
controlled extraction/retrieval comparisons, a captured public regression, and selected
actual notebook cells with controlled collaborators. The optional local Markdown
regression skips when its ignored source file is absent. A core install can skip ML-only
cases; `make test-ml` explicitly enables their dependencies. Full notebook runs and live
model accuracy are separate from these checks.

## Credit perspective reviews

The [review workflow regressions](../tests/integration/workflows/test_credit_review.py)
exercise real assessments and PydanticAI execution with scripted model boundaries.
They verify single-borrower scope, parallel independent reviews, complete rationale
handoff, argument/evidence references, ML and news limitations, failures, and serialization.
They do not establish live argument quality or the suitability of credit recommendations.

The [review usage guide](credit_review.md#validation-and-model-evaluation) describes
representative opt-in live cases and evaluation criteria. Capture full typed review
results so both arguments and the synthesizer's judgments remain inspectable. No live
calls or new judge infrastructure are added to the portable suite.

## Public-cache quality

The [SEC comparison guide](../tests/evaluation/extraction/README.md) documents read-only
snapshot creation, completeness reports, supported/unsupported targets, and replay:

```bash
uv run --locked python scripts/compare_public_sec_gold.py \
  --database data/processed/covenants.sqlite3 \
  --output /tmp/public-sec-comparison --require-complete-sources
```

Use an existing database and a fresh output directory for each measurement. A supported
mismatch, missing core fact, or wholly unevaluable comparison exits nonzero. The
[failure register](public_sec_benchmark_triage.md) retains the review's historical 37
failures. Passing portable tests does not clear these quality issues.

## Live homework scenarios

[Homework tests](../homework-tests/README.md) retain ordinary tool/date assertions and
a small PydanticAI final-answer judge. They run only with `--run-live` or its alias
`--run-llm-evals`, require credentials, and retain captured failures. Offline helper
regressions run by default and do not measure judge calibration. Historical live
measurements retain their dates; later refactors do not imply a fresh live pass.

## Optional Evidently checks

Evidently evaluates captured extraction, retrieval, and answer snapshots, including
credentialed judge calls when explicitly requested. Its mocked test suite is isolated
from the core runtime in Python 3.13:

```bash
uv sync --project tools/llm_judges --group dev --locked
make test-judges
make lint-judges
```

Do not collect both environments in one pytest process. `make check` runs the root and
isolated commands separately, including ML coverage. See [LLM judges](llm_judges.md) for
capture APIs, rubrics, commands, reports, and limits. Structured verification does not
prove arbitrary prose correct. Logfire monitoring and fuller agent evaluation remain
later learning work.
