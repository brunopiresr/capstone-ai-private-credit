# Human evaluation app

```bash
uv run --locked streamlit run homework/evaluation/app.py
```

Use the project environment and configure `OPENAI_API_KEY` in the root `.env`.
`LLM_MODEL` optionally overrides `openai-responses:gpt-4o-mini`.

## Rate answers

1. **Start evaluation** previews the first question.
2. **Run question** generates an answer and incurs provider usage.
3. Select a category, optionally add a comment, then **Submit and next**.
4. Use **Retry answer** after a failed/incomplete response, or **Skip** to move on
   without generating or rating an answer.

Categories are Correct, Incorrect, Incomplete, Unsupported claims, Irrelevant, Unclear,
and Unable to evaluate. There is no default selection. Response ratings are separate
from question categories.

The app presents all 27 prepared cases in order, including development and holdout.
Each gets a fresh scoped agent; reference answers and prior labels stay hidden.
Use the [CLI exercise](2026-10-26/README.md) for controlled dev/holdout experiments.
All cases passed source preflight after exhibit preparation on 29 October 2026.

## Pause or restart

**Cancel / restart** opens a summary. **Continue evaluating** returns to the current
answer; **Proceed to restart** starts a new round at question 1. Finishing the last
question also opens the summary. Unsent feedback is discarded on restart.

Browser refresh can lose in-memory progress. Submitted records remain in ignored
`2026-10-26/runs/human-<round-id>/`, with answer hashes, model, IDs, rating, comments,
and timestamps. Skips are saved separately and excluded from evaluated counts.

## Telemetry and checks

Optional [Logfire](../../docs/guides/monitoring.md) links requests and feedback by
`chat_id`, `case_id`, and `interaction_id`. Filter `event_name = 'user.feedback'`.
Question/comment content follows `LOGFIRE_CAPTURE_CONTENT`; local feedback always
retains the submitted comment. Local saving works without telemetry credentials.

```bash
uv run --locked pytest homework/evaluation/tests homework/evaluation/2026-10-26/test_workbench.py
```
