# Evaluation exercise

For the interactive rating app, see [Human evaluation app](../README.md).
The two previously missing SEC exhibits were prepared on 2026-10-29; all 27 questions
now pass source preflight. Historical run snapshots retain their original gaps and labels.

Start with the prepared cases and commands below. New runs create ignored local
outputs; a clean checkout does not include historical live responses or credentials.
The historical baseline recorded **19 failed, 5 passed, 3 insufficient evidence**.
Its preserved local reports remain under `runs/baseline-live/` when available;
these counts were not rerun during this structural cleanup.

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
EVAL=homework/evaluation/2026-10-26/workbench.py
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

All authored cases and prepared sources remain versioned. Existing local responses,
traces, consolidated labels and judge results were preserved during the move.
New runs require new names. Missing sources remain blocked; see [GAPS-data.md](GAPS-data.md).
Prepared data are reused and databases stay inside each new run.

The only folders are `data/` (inputs) and `runs/` (local outputs, ignored by Git).
Reports, diagnostics, historical rubrics and test scratch files belong inside `runs/`.
Obsolete framework code and duplicate labels have been removed. The saved plan is historical;
this README describes the current code.

Offline checks for this script are in `test_workbench.py`:

```bash
mkdir -p homework/evaluation/2026-10-26/runs
.venv/bin/python -B -m pytest homework/evaluation/2026-10-26/test_workbench.py \
  -p no:cacheprovider --basetemp=homework/evaluation/2026-10-26/runs/.test-tmp -q
```
