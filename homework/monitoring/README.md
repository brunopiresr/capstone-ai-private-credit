# Monitoring chat demo

A Streamlit exercise for observing shared agents and user activity with optional Logfire.
For the main project workspace, use the [README](../../README.md).

```bash
uv sync --extra ml --group dev --locked
uv run --locked streamlit run homework/monitoring/app.py
```

Configure `OPENAI_API_KEY` in the root `.env`; `LLM_MODEL` overrides the default
`openai-responses:gpt-4o-mini`. See [Logfire setup](../../docs/guides/logfire_setup.md)
for telemetry. Chat needs model credentials; telemetry is optional.

## Modes

- **Evidence Search** discovers sources and searches local SEC Markdown. Its tools
  exclude downloads and extraction; prepare sources separately.
- **Credit Analysis** uses synthetic borrower financials, calculations, optional ML,
  bullish/bearish reviews, and recommendation. Supply borrower, period, cutoff, and
  criteria. If ML is unspecified, it uses Logistic Regression and discloses that choice.

Examples fill an editable draft; sending runs the question. Answers retain activity,
tools, citations, calculations, and review results. Follow-ups reuse completed reviews;
changed inputs or an explicit refresh can request a new one. Ordinary reruns do not.
Missing inputs, failed reviews, and unavailable forecasts remain visible.

Both modes share one telemetry session but keep separate chat histories. **Reset session**
clears histories, cached reviews, and drafts, then starts a new session. Exported traces
and local diagnostic files remain. Runtime databases live in `data/runtime/monitoring/`.

## User events

Events share `event_name`, `chat_id`, mode, UTC time, question count, and timing snapshots.
Answer events include `interaction_id` to join to `chat.interaction` and model/tool traces.

| Events | Meaning |
| --- | --- |
| `user.started`, `user.ended` | Start and explicit end on reset; new starts link `previous_chat_id` |
| `user.reset_context` | Cleared context, affected modes, and last answer |
| `user.click` | Example selection, mode change, retry, or source click |
| `user.question_submitted`, `user.follow_up` | Question length, turn, prior answer, and user-selected follow-up type |
| `user.answer_presented` | Response time, completion, and error type |
| `user.retry` | Explicit retry and preceding failure |
| `user.feedback` | Rating, optional reason, and comment presence |

**Rate this answer** submits feedback; **View citation** records an explicit source click.
Reruns do not repeat these actions. Use the latest feedback per interaction. Unspecified
follow-up type is not inferred intent; New topic sets `is_follow_up=false`.
Question/comment text follows `LOGFIRE_CAPTURE_CONTENT`. Answers, citation bodies, and
exception messages are not copied into user events.

Timing fields are cumulative: use the latest/max snapshot per chat, never sum them.
`elapsed_seconds` is wall time; `observed_duration_seconds` ends at the latest action.
`active_seconds` sums action gaps up to five minutes, excluding longer gaps and agent
wait time. Tab closure may not emit an end event. Session-anchor duration is unrelated
to engagement. Clicks, follow-ups, and duration alone do not establish answer quality.

Use negative feedback, corrections, repeated retries, and resets as candidates for
reviewed evaluation cases. Credit inputs and the trained model are synthetic; they are
not mapped to real SEC issuers.

```bash
uv run --locked pytest -q homework/monitoring/tests
```

Tests use scripted providers and disable export. They are included in `make test-homework`.
The demo styling references [AI Shipping Labs](https://aishippinglabs.com/).
