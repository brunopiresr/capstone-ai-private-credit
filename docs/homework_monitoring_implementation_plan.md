# Simple Streamlit chat for testing Logfire

## Purpose and delivery order

Build a small chat prototype in `homework-monitoring` to test agent monitoring
and the concept of the final application. Use native Streamlit controls and
minimal HTML, styled after AI Shipping Labs (Inter, dark neutral surfaces, lime
accents, thin borders), without reusing the full analyst dashboard.

**The shared Logfire dependencies, configuration, context, and monitoring helpers
will be implemented by another coding agent**, following
[the platform monitoring plan](logfire_implementation_plan.md). Do not duplicate
that implementation or change its dependencies as part of the UI-only step.

## Step 1: runnable UI and navigation

- Provide **Evidence Search** and **Credit Analysis** modes with independent chat
  histories in Streamlit session state. Switching modes retains the UI session.
- Show a small static HTML header, mode navigation, chat input, chat messages,
  current UI session ID, and an always-visible **Reset session** button.
- Both modes take their inputs only from the user's prompt. Credit Analysis has
  no required form. A **Help** button opens guidance for including borrower ID,
  reporting period, information cutoff, ML preference, and credit criteria.
- Show five sample questions per mode in a panel on the right. Each has a short,
  clickable title; clicking copies the full prompt into the editable chat input
  without submitting it. Sample credit prompts include explicit dates and criteria.
- Accept messages and return clearly labeled placeholder replies. Show that no
  tools were called and no trace was sent. Do not fabricate analysis or telemetry.
- Reset clears both mode histories and chat inputs, replaces the UI session ID,
  and retains the current mode. State belongs to each browser session.
- Keep the UI runnable with existing dependencies and without API credentials,
  database access, model loading, or Logfire imports.

Run from the repository root:

```bash
uv run --locked streamlit run homework-monitoring/app.py
```

Validate navigation, separate mode histories, sample selection without submission,
editing/sending copied questions, placeholder replies, reset behavior,
browser-session isolation, and clean startup using Streamlit `AppTest`.

## Step 2: connect agents after shared Logfire is available

### Evidence Search

- Use one named evidence agent with document discovery and local evidence-search
  tools, reusing existing document-tool methods and retrieval services.
- Resolve the prompt's company/ticker against the SEC catalog and search existing
  local Markdown. Return cited passages and answers; report missing evidence explicitly.
- Keep downloads and extraction outside this search workflow.

### Credit Analysis

- Use synthetic borrower data through the existing assessment workspace, with
  dedicated ignored runtime SQLite storage beneath `homework-monitoring`.
  Keep existing databases untouched.
- Resolve borrower, reporting period, information cutoff, ML preference, and credit
  criteria from user messages. Ask in chat for missing required details; do not
  substitute form values or silently assume dates or credit criteria. Clearly
  label synthetic data and demo criteria supplied in sample prompts.
- On the first sufficiently specified question, pass that question and its criteria as
  `ExposureDecisionContext` and run the existing credit-review workflow:
  SQLite financials → deterministic calculations and verification → features and
  ML → concurrent bullish/bearish agents → recommendation.
- Display assessment results, perspectives, recommendation, and limitations in
  the assistant message. Preserve existing blocked, incomplete, deferred, and
  unavailable-ML outcomes; deterministic results remain visible on ML failure.
- Answer subsequent questions with a small named chat agent supplied with the
  completed structured review and its own conversation history. Do not rerun the
  full review for follow-ups.
- A prompt changing issuer or analysis inputs invalidates the affected review;
  the next sufficiently specified analysis runs a new review. Mode changes retain independent
  histories within the same monitoring session.
- Execute only on question submission; ordinary reruns must not repeat work.

### Monitoring integration points

The platform owns the mechanisms below. The prototype consumes them once ready.

| Interaction requirement | Integration needed |
|---|---|
| One session across questions and mode changes | Retain one shared `SessionContext` in Streamlit session state. Replace the temporary UI UUID with its session ID. |
| One trace across Streamlit reruns | Reattach the shared context carrier for every submitted question; equal session attributes alone do not establish parentage. |
| Every question is observable | Create one `chat.interaction` span per submission with mode, interaction ID, applicable business identifiers, and outcome. |
| Agents and tools are visible | Use central PydanticAI instrumentation and the shared session ID as `conversation_id`. |
| Calculations, ML, and review are visible | Consume the platform's workflow spans and logging bridge, retaining parentage through worker threads and concurrent reviewers. |
| Tools are visible in the chat | Render actual executed tool events/results; distinguish service workflow stages from model tool calls. Explicitly show when none ran. |
| Failures remain observable | Record handled incomplete outcomes as well as escaping exceptions through shared monitoring conventions. |
| Reset starts independent monitoring | Close conversations, clear cached reviews and histories, and create a new `SessionContext`; retain exported telemetry. |

One user session has one session ID and one trace ID. Each interaction is a child
span in that trace, not an independent trace. Nested service scopes retain the
active parent. The short session anchor does not measure total session duration.

Keep content capture disabled unless `LOGFIRE_CAPTURE_CONTENT=true`. Use native
model-request token usage and derive session totals in Logfire, including retries
and reviewers without double counting. Do not add local telemetry storage, token
counters, duplicate SDK instrumentation, or per-question exporter flushing.

The shared initializer must support repeated Streamlit startup, no-token/offline
usage without authentication prompts, and background export. Refer to the
platform plan for its exact configuration and implementation contracts.

## Integration acceptance checks

- Five questions across reruns retain one session and trace. Reset creates both
  identifiers anew and clears both modes. Independent browsers stay isolated.
- Evidence search shows actual executed tools and citations without extraction.
- First analysis runs the full workflow once; follow-ups reuse it; input changes
  invalidate it and cause the next question to run a new review.
- Calculations in worker threads and concurrent reviewers retain correct parents.
- Success, handled failures, cancellation, and interrupted consumption restore
  tracing context. Repeated setup adds no duplicate handlers/instrumentation.
- Ordinary tests use scripted models, temporary storage, and Logfire in-memory
  utilities with network export explicitly disabled.
- Disabled content capture retains metadata and usage. Existing conversation,
  streaming, review, logging, and UI regressions continue to pass.
- With credentials, smoke-test evidence search, full analysis, follow-up, and reset;
  inspect session grouping, nesting, errors, and usage directly in Logfire.
  Report cloud verification as outstanding if credentials are unavailable.

Authentication, persistent chat storage, custom analytics dashboards, and production
deployment remain outside this prototype.
