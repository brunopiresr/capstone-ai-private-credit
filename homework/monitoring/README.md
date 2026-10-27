# Monitoring chat demo

A simple Streamlit chat for testing agent activity in Logfire. This is a demo,
not the final application. It uses the shared platform monitoring implementation.

From the repository root:

```bash
uv sync --extra ml --group dev --locked
uv run --locked streamlit run homework/monitoring/app.py
```

Configure `OPENAI_API_KEY` in the repository `.env`. `LLM_MODEL` optionally changes
all chat/review agents; the default is `openai-responses:gpt-4o-mini`.
See [Logfire setup](../../docs/guides/logfire_setup.md) for `LOGFIRE_TOKEN`, region,
export settings, and content capture. Without a Logfire credential the SDK can
run locally; without a model credential the UI explains setup and disables chat.
Content capture follows `LOGFIRE_CAPTURE_CONTENT`, disabled by default. Configuration
status is not a claim that cloud transport or the Logfire UI has been verified.

Select a mode using the large buttons above the chat. Each has a short description;
the selected mode is light green with a check icon. The playground uses a light gray
background, white cards, and dark text, including when a browser has retained a dark
Streamlit theme preference. **Help** provides prompting guidance.
The five titled examples on the right copy a full question into chat for editing.
They do not submit or execute anything until you send the question.

- **Evidence Search:** one evidence agent discovers documents and searches local
  SEC Markdown. Answers include actual citations and tool outcomes. Downloads,
  extraction, and document processing are excluded from this demo's tool allowlist.
- **Credit Analysis:** describe the synthetic borrower, reporting period,
  information cutoff, ML preference, and credit criteria in your prompt. The chat
  asks for missing required details, then invokes the existing assessment and
  review services. Financial retrieval, deterministic calculations, ML, concurrent
  bullish/bearish agents, and recommendation all remain in the platform. If ML is
  unspecified, the default is Logistic Regression; the reply must disclose it.

Live activity appears inside each assistant message. The answer streams while it
is generated. Activity, tools, citations, calculations, verification, ML results,
reviewer outputs, recommendation, and evidence remain available after reruns.
Only public progress and analytical outputs appear; private model reasoning is
excluded. Missing data, unavailable ML, blocked verification, reviewer failures,
and deferred recommendations remain explicit.

Credit follow-ups use the completed review without recalculating it. Changed
borrower/dates/ML/criteria or an explicit refresh request can run a new review.
Identical tool requests reuse the cached result unless refresh was requested.
Ordinary Streamlit reruns never execute another interaction.

Both modes share one `SessionContext` and Logfire trace, with a separate
`chat.interaction` span per submitted question. Its displayed message includes the
chat mode, agent name, session label, and session ID. Evidence `agent.turn` messages
include the agent name, session label, and session ID. The stable span names remain
available for filtering, alongside structured `agent_name`, `chat_name`, and
`chat_id` attributes. Both modes keep separate conversation histories.
**Reset session** closes conversations, clears both histories, reviews
and unsent drafts, and creates a new session/trace while retaining the selected
mode. Already exported telemetry is retained. Browser sessions are isolated.

The demo also logs user actions to the same session trace. Every event includes
`event_name`, `chat_id`, mode, UTC event time, question count and timing
snapshots. Answer-related events include `interaction_id` for joining to
`chat.interaction`. The Logfire span name, message template and message use the event
name directly (for example, `user.feedback`). Retained browser trackers are refreshed
on reruns and callbacks so code reloads use the current emitter without losing chat
history or timing. Previously exported records keep their original names.

| Event | What we collect | How we use it |
| --- | --- | --- |
| `user.started`, `user.ended` | Start, explicit end on reset, question count and duration. New starts include `previous_chat_id` after a reset. | Compare time and effort across workflows; connect the old and new contexts. |
| `user.reset_context` | **Reset session** action, old chat ID, last answer ID in the selected mode, number of cleared turns and affected modes. | Find resets after errors or poor feedback; investigate lost context or confusing answers. |
| `user.click` | Selected sample index, mode change, retry click, or opened source index. | Identify useful entry points and whether users inspect supporting citations. |
| `user.question_submitted` | Turn number, question length and previous answer ID within the selected mode. | Measure questions per workflow and link actions to the answer being evaluated. |
| `user.follow_up` | Previous answer ID, optional user-selected question type and previous error. | Find unclear explanations, corrections and missing detail; use reviewed examples to improve prompts and evaluations. |
| `user.answer_presented` | Response time, completion/error status and stable error type. | Separate slow responses from failures and trace the responsible agent or tool. |
| `user.retry` | Explicit retry, failed answer ID, error type and delay before retry. | Check whether another attempt succeeds and prioritize recurring failures. |
| `user.feedback` | Thumbs up/down, optional reason and whether a comment was entered. | Review negative answers, track recurring problems and build regression evaluation cases. |

Follow-up type is supplied by the user: `Unspecified` is not an inferred intent;
`New topic` sets `is_follow_up=false`. Reset clears both modes' conversation
histories and cached reviews, then creates a new chat ID. It emits one
`user.reset_context` on the old trace before `user.ended`, followed by `user.started`
on the new trace.

For evaluation, group feedback reasons and errors by mode, compare response times,
and follow the interaction IDs into model/tool traces. Review negative feedback,
correction requests, repeated retries and resets as candidate failures before
adding them to evaluation cases. Use those cases to test prompt, retrieval or tool
changes. A follow-up, source click, long session or reset alone is not proof that an
answer was wrong.

Use **Rate this answer** to submit feedback and **View citation** to inspect a
source. A normal rerun neither resubmits feedback nor records another source click.
Only submitted questions and feedback comments follow `LOGFIRE_CAPTURE_CONTENT`;
they are omitted when it is false. Citation text, model answers, and exception
messages are not copied into user events. Feedback changes are explicit new
submissions; use the latest feedback per interaction when calculating satisfaction.

`chat_id` matches the application's session ID and `gen_ai.conversation.id`. Event
names and attribute keys avoid the word `session`, which the SDK's default secret
scrubber removes; scrubbing stays enabled.

`elapsed_seconds` measures wall time since UI initialization.
`observed_duration_seconds` ends at the latest user action. `active_seconds` is an
estimate: it sums gaps of at most five minutes between observed actions, excludes
longer idle gaps, and excludes waiting for agent responses. These are cumulative
snapshots: use the latest/max value per session, rather than summing events.
Timing updates on actions; closing a browser tab does not reliably emit an end
event. Use the last observed snapshot for those sessions. Session-anchor span
duration is unrelated to user engagement. Clicks and duration alone do not establish
answer correctness or satisfaction.

Runtime SQLite files live under ignored `data/runtime/monitoring/<session-id>`;
existing processed databases are not overwritten. Reset releases in-memory state
but does not delete these diagnostic files. Credit inputs and ML training data are
synthetic; no relationship to real SEC issuers is inferred. The Logistic Regression
artifact must exist at `data/models/logistic_regression/v1`; an unavailable artifact
leaves deterministic results visible with an explicit ML failure.

`app.py` owns UI/session state, `monitoring_backend.py` adapts the platform agents,
`chat_rendering.py` displays results, and `index.html` supplies the styling inspired
by [AI Shipping Labs](https://aishippinglabs.com/).

Run the demo's offline checks:

```bash
uv run --locked pytest -q homework/monitoring/tests
```

These tests use scripted provider responses and temporary data, explicitly disable
network export, and include a fresh-process Logfire hierarchy check. They are also
included in `make test-homework`, `make test-all`, and `make lint`.
