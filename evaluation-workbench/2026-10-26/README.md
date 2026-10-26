# Evaluation exercise

Start with the [local failure report](runs/baseline-live/FAILURES.md):
**19 failed, 5 passed, 3 insufficient evidence**.

There is one script, `workbench.py`, with three commands. It uses the project's existing
Python environment and PydanticAI; no separate judge environment is needed.

| What | Where |
|---|---|
| Questions and expected behavior | `cases.jsonl`, `references.jsonl` |
| Categories | [CATEGORIES.md](CATEGORIES.md), `classifications.jsonl` |
| Judge rubric | `rubrics.json` |
| Input documents and financial fixtures | `data/` |
| Original agent responses and tool traces | `runs/baseline-live/<case>/answer.json` |
| Business Agent labels | `runs/baseline-live/labels.jsonl` |
| Previous judge responses | `runs/baseline-live/judges/` |

From the repository root:

```bash
EVAL=evaluation-workbench/2026-10-26/workbench.py
.venv/bin/python -B "$EVAL" summary baseline-live
.venv/bin/python -B "$EVAL" run new-run --env-file .env
# Business Agent reviews responses and writes runs/new-run/labels.jsonl first.
.venv/bin/python -B "$EVAL" judge new-run --name first-judge --env-file .env
.venv/bin/python -B "$EVAL" summary new-run --judge first-judge
```

Labels contain `case_id`, `label`, `explanation`, and the `response_sha256` from
`records.jsonl`. Allowed labels: `pass`, `fail`, `insufficient_evidence`. Business
labels are specialist-agent reviews, not human annotations. Labels never enter judge prompts.

Use `--cases A07,A08` or `--split dev` for a subset. Judge only development cases while
adjusting its rubric; reserve holdout for a final check. The existing judge remains
unaligned. No new live runs or agent repairs were performed during simplification.

All evaluation cases, responses, traces, consolidated labels and judge results are preserved.
New runs require new names. Missing sources remain blocked; see [GAPS-data.md](GAPS-data.md).
Prepared data are reused and databases stay inside each new run.

The only folders are `data/` (inputs) and `runs/` (local outputs, ignored by Git).
Reports, diagnostics, historical rubrics and test scratch files belong inside `runs/`.
Obsolete framework code and duplicate labels have been removed. The saved plan is historical;
this README describes the current code.

Offline checks for this script are in `test_workbench.py`:

```bash
mkdir -p evaluation-workbench/2026-10-26/runs
.venv/bin/python -B -m pytest evaluation-workbench/2026-10-26/test_workbench.py \
  -p no:cacheprovider --basetemp=evaluation-workbench/2026-10-26/runs/.test-tmp -q
```
