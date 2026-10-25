# Monitoring chat demo

A simple Streamlit chat for testing agent activity in Logfire. This is a demo,
not the final application. It uses the shared platform monitoring implementation.

From the repository root:

```bash
uv sync --extra ml --group dev --locked
uv run --locked streamlit run homework-monitoring/app.py
```

Configure `OPENAI_API_KEY` in the repository `.env`. `LLM_MODEL` optionally changes
all chat/review agents; the default is `openai-responses:gpt-4o-mini`.
See [Logfire setup](../docs/logfire_setup.md) for `LOGFIRE_TOKEN`, region,
export settings, and content capture. Without a Logfire credential the SDK can
run locally; without a model credential the UI explains setup and disables chat.
Content capture follows `LOGFIRE_CAPTURE_CONTENT`, disabled by default. Configuration
status is not a claim that cloud transport or the Logfire UI has been verified.

Select a mode using the large buttons above the chat. Each has a short description;
the selected mode is lime with a check icon. **Help** provides prompting guidance.
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

Runtime SQLite files live under ignored `homework-monitoring/runtime/<session-id>`;
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
uv run --locked pytest -q homework-monitoring/tests
```

These tests use scripted provider responses and temporary data, explicitly disable
network export, and include a fresh-process Logfire hierarchy check. They are also
included in `make test-offline` and `make lint`.
