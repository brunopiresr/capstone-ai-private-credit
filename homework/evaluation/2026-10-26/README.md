# Evaluation exercise: 26 October 2026

A prepared 27-case experiment for evidence search, document processing, and credit
analysis. Use the [human rating app](../README.md) for interactive review.

All cases passed source preflight after the missing full exhibits were prepared on
29 October 2026. The historical baseline recorded **19 fail, 5 pass, 3 insufficient
evidence**; these scores have not been rerun here. Ignored local responses are absent
from a clean checkout.

| Input | Purpose |
| --- | --- |
| `cases.jsonl`, `references.jsonl` | Questions and expected behavior |
| [CATEGORIES.md](CATEGORIES.md), `classifications.jsonl` | Question taxonomy and coverage |
| `rubrics.json` | Judge rubric |
| [DATA.md](DATA.md), `data/` | Prepared runtime inputs and provenance |
| `runs/` | Ignored answers, traces, labels, and judge output |

## Run and review

From the repository root, with model credentials configured:

```bash
EVAL_SCRIPT=homework/evaluation/2026-10-26/workbench.py
uv run --locked python "$EVAL_SCRIPT" run new-run --env-file .env
# Review answers and write runs/new-run/labels.jsonl before judging.
uv run --locked python "$EVAL_SCRIPT" judge new-run --name first-judge --env-file .env
uv run --locked python "$EVAL_SCRIPT" summary new-run --judge first-judge
```

Use new run names. `--cases A07,A08` or `--split dev` selects a subset. Tune on development
cases only; reserve holdout for a final check. The judge remains unaligned.

Labels require `case_id`, `label`, `explanation`, and the `response_sha256` from
`records.jsonl`. Labels are pass, fail, or insufficient_evidence. Historical Business
Agent labels are specialist-agent reviews, not human annotations, and never enter
judge prompts. Prepared sources are reused; databases stay inside each run.

See [data limitations](GAPS-data.md) and the [historical plan](PLAN.md).
Offline checks: `uv run --locked pytest homework/evaluation/2026-10-26/test_workbench.py`.
