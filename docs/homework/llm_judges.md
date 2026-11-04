# LLM judges with Evidently

Three optional judges evaluate captured extraction, retrieval, and answer outputs.
They run after an experiment and do not change application results or gate the UI.

| Judge | Checks |
| --- | --- |
| Extraction | Facts, attribution, schedules, quotations, and omissions against processed source passages |
| Retrieval | Relevance, issuer, and dates; recall only when a reviewed reference is supplied |
| Answer | Task completion, source support, citations, uncertainty, and actual tool results |

Exact arithmetic and field comparisons remain deterministic tests. Judge labels are
opinions requiring calibration, not proof of correctness.

## Environment and commands

Evidently uses a separate Python 3.13 environment under `homework/llm-judges/` because
its integration was incompatible with the project's Python 3.14 runtime.

```bash
uv sync --project homework/llm-judges --group dev --locked
uv run --locked python scripts/run_evaluation.py \
  --input data/evaluation/judges/demo_cases.jsonl --dry-run
```

For model judging, configure `OPENAI_API_KEY` or explicitly load `.env`:

```bash
uv run --locked python scripts/run_evaluation.py \
  --input data/evaluation/judges/demo_cases.jsonl --env-file .env \
  --output-dir data/runtime/judges-demo
```

This sends selected snapshots to the configured model through Evidently; it does not
upload to Evidently Cloud. Defaults use `gpt-4o-mini`. Options include `--judge answer`,
`--model`, `--limit`, and `--max-input-chars`. `--model` overrides `EVIDENTLY_JUDGE_MODEL`.
Use distinct output directories to preserve experiments.

## Snapshot contract

The runner accepts JSONL of observed outputs, not benchmark questions alone.

| Field | Contents |
| --- | --- |
| `case_id`, `judge`, `question` | Identity, judge role, and requested scope |
| `output` | Captured text or JSON-encoded result; null/blank is skipped, `[]` is a completed empty retrieval |
| `context` | Actual source passages with `document_id`, `citation`, and `text`; optional ticker/offsets |
| `tool_trace` | Actual tool calls and returned data |
| `reference` | Optional evaluator-only comparison target, added after generation |
| `metadata` | Scope, prompt version, dates, or structured assessment context |
| `expected_label` | Optional reviewed label for calibration; excluded from judge prompts |

Unknown fields and duplicate `(case_id, judge)` pairs are rejected. Inputs above the
default 100,000-character budget are skipped, never silently truncated. Scope large
filings to the sections actually reviewed. Preserve unknown source availability and
exclude later outcomes, benchmark notes, and labels from generating inputs.

The nine supplied demo cases are hand-authored synthetic examples with deliberate
failures. They demonstrate integration, not public benchmark or production accuracy.

## Capture outputs

Use adapters from `credit_monitoring.evaluation.judge_inputs`:

- `capture_extraction`: result plus the original processed text.
- `capture_retrieval`: question plus the returned passages.
- `capture_answer`: answer plus its actual evidence and tool trace.
- `write_judge_inputs`: save the records as JSONL.

Capture the evidence used by that run; a later search is not a substitute. For an
assessment summary, attach `assessment_context(assessment)` in
`metadata["assessment_context"]`. Incomplete agent answers export null output and
failure metadata. Add reviewed references only after generation.

## Read results

Labels are `pass`, `fail`, or `insufficient_evidence`; execution status is separately
`evaluated`, `skipped`, or `error`. Failures never become quality passes.

Outputs include selected inputs, per-case results, a summary, a reproducibility
manifest, and local HTML/JSON reports. Pass rate uses decisive pass/fail judgments;
coverage also shows skips, errors, and insufficient evidence. Manual-label agreement
measures judge alignment, not credit-model accuracy.

A completed evaluation exits 0 even with failed candidates. `--fail-on-quality` returns
1 for failed, insufficient, or skipped cases. Input/provider/report errors return 2.
The demo intentionally fails a strict quality gate.

```bash
make test-judges
make lint-judges
uv run --locked pytest tests/unit/evaluation -q
```

Tests use mocked model replies. Historical smoke runs exercised all three judges;
a cached FMC extraction received a failure flag. That remains a review finding,
not a confirmed legal interpretation. See [public SEC findings](../reviews/public_sec_benchmark_triage.md).
