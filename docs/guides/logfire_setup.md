# Logfire setup and validation

The application uses Logfire's public configuration, logging, context, and native
PydanticAI APIs. The CLI, notebooks, and Streamlit initialize it after loading their
environment. Library imports and service factories do not initialize monitoring.

Copy the Logfire settings from [.env.example](../../.env.example) into the repository
`.env`, using the existing EU project's credential with permission to send telemetry:

```dotenv
LOGFIRE_TOKEN=
LOGFIRE_BASE_URL=https://logfire-eu.pydantic.dev
LOGFIRE_SERVICE_NAME=credit-monitoring
LOGFIRE_ENVIRONMENT=development
LOGFIRE_SEND_TO_LOGFIRE=if-token-present
LOGFIRE_CAPTURE_CONTENT=false
LOGFIRE_MIN_LEVEL=info
```

Keep credentials and `.logfire/` outside source control. Without credentials,
`if-token-present` leaves deterministic workflows usable. It can discover locally
stored SDK credentials; set `LOGFIRE_SEND_TO_LOGFIRE=false` to explicitly disable
export, including in offline environments. The assessment CLI loads the repository
`.env` with `override=False`, preserving exported environment variables.

`LOGFIRE_CAPTURE_CONTENT` accepts only `true` or `false`, ignoring whitespace and case.
It defaults to `false`. Binary content capture remains disabled. Native metadata and
available usage remain visible. Custom application logs retain explicit projections;
disabling native content capture does not scrub arbitrary application log messages.
Keep the SDK's default secret scrubbing enabled.

`LOGFIRE_MIN_LEVEL` controls the SDK cloud threshold. Console verbosity remains
independent through `configure_logging()` and the CLI's `--log-level`. Cloud DEBUG
can coexist with console WARNING. CLI stdout remains assessment JSON; its shutdown
uses bounded SDK flushing. No per-question flushing is needed.

## Library and conversation examples

```python
from dotenv import load_dotenv
from credit_monitoring.observability import (
    SessionContext, configure_observability, session_scope,
)

load_dotenv(override=False)
configure_observability()

# With an existing CreditAssessmentAgent and configured assessment service:
session = SessionContext(name="Quarterly review — SYN002")
conversation = agent.start_conversation(borrower_id="SYN002", session=session)
first = conversation.ask("Assess 2025-09-30 using the same information cutoff.")
second = conversation.ask("Explain the reported headroom.")
print(conversation.session_id)
conversation.close()

# Standalone services automatically establish a session. To group several calls:
with session_scope(SessionContext(name="Covenant assessment — SYN002")):
    assessment = assessment_service.assess(borrower_id, period_end, information_cutoff)
```

`SessionContext(name=...)` sets the session's displayed message in Logfire. Names
default to `Credit assessment`; surrounding whitespace is trimmed and blank names
raise `ValueError`. The queryable span name remains `agent.session`, so existing
filters continue to work. `agent.turn` messages include the agent name, session label,
and session ID, for example `Agent turn: Credit assessment agent — Quarterly review —
SYN002 [chat <session-id>]`. Native `invoke_agent` spans are unchanged.

In the monitoring demo, `chat.interaction` messages also include the chat mode and
the coordinating agent's name. Both span types retain their stable queryable names;
`agent_name`, `chat_name`, and `chat_id` are structured attributes. The chat ID
matches `gen_ai.conversation.id`; the mode distinguishes the demo's two chat histories
within the shared session. Resetting the session creates a new chat ID.

Set the name before the first configured execution scope creates the session anchor.
Explicit and inherited sessions keep their supplied name, and subsequent turns reuse
the same anchor and displayed message. Changing `session.name` after that point does
not rename the existing anchor. Names are explicit telemetry metadata, independent of
the native content capture setting; questions and borrower details are not added
automatically. Historical traces keep their original labels.

The monitoring demo also records feedback, UI clicks, questions/follow-ups, explicit
retries, context resets, response outcomes and session timing as structured Logfire **log records**
under the same session trace. Filter by the `event_name` attribute (for example,
`user.feedback`) and join `interaction_id` to `chat.interaction` to investigate the
answer's tools, errors, latency and native model usage. Question text and feedback
comments respect `LOGFIRE_CAPTURE_CONTENT`. See the demo's
[user-event fields and timing limits](../../homework/monitoring/README.md) before
aggregating engagement or feedback metrics. The **Reset session** button emits
`user.reset_context` on the old chat trace; the new chat's `user.started` event links
back through `previous_chat_id`. New records use their concrete event name as the
span name and message; historical exported names are unchanged.

Use `await conversation.ask_async(...)` when an event loop is already running.
Streamlit retains the same conversation object and session across reruns. Direct
stream consumers must close generators in the consuming task, including on early exits:

```python
from contextlib import aclosing

async with aclosing(conversation.stream_async("Explain these results.")) as stream:
    async for event in stream:
        if should_stop:
            break
```

The assessment facade's `tracing_enabled=None` inherits central native instrumentation.
`False` disables native instrumentation for that agent; `True` uses the central content
policy. Workflow spans remain independently controlled by monitoring configuration.

## Checks

```bash
make lint
make test-offline
uv run --locked python scripts/validate_logfire.py
# Only after configuring local EU credentials:
uv run --locked python scripts/validate_logfire.py --live
```

Automated tests cover application-owned helpers and use cases with SDK boundaries
stubbed; ordinary tests explicitly disable export. The separate validation script uses
Logfire's in-memory testing API in a fresh process. Its offline mode also guards network
connections during configuration and execution. Neither mode calls a live model or SEC.

To export just the five-turn conversation test, run it in a fresh pytest process with
the explicit opt-in flag:

```bash
.venv/bin/python -m pytest tests/unit/covenants/test_conversation_sessions.py::test_five_synchronous_turns_share_retained_session_and_leave_idle_context_clear --conversation-logfire -v
```

This loads the repository `.env`, configures monitoring before the first turn, and
flushes telemetry at teardown, including when an assertion fails. Without `--conversation-logfire`,
the test remains offline. An initialized session retains its propagation carrier;
idle cleanup restores the active session and SDK context between turns.

The script checks the ended-anchor carrier gate; five synchronous conversation turns
across separate event loops; nested tool/thread/calculation and review parenting;
session isolation and restoration; callback failures, cancellation, and interrupted
streams; document processing and RAG; native usage across retries and multiple agents;
disabled content capture; and idempotent configuration/handler registration. Token
numbers in this smoke run come from scripted models, rather than paid provider calls.

Live mode runs the same synthetic scenario, verifies its emitted hierarchy and confirms
successful EU trace transport responses. Its JSON result includes the conversation's
`trace_id` and `session_id`. Inspect that trace in the EU project to confirm backend
display and Agents-view grouping; the script does not query the project or automate its UI.

One ended session anchor parents all resumed turns. Its duration does not measure
conversation elapsed time, and its status does not summarize subsequent failures.
Inspect turn/workflow errors and timings. Sum native model-request
`gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`, including retry and nested
agent requests; exclude agent aggregate fields from those totals. Unavailable usage
remains unknown. Default sampling remains unchanged.

See [implementation decisions](../project/decisions/logfire_implementation_decisions.md) for ownership and
scope. Dashboards, alerts, HTTP/query tracing, custom exporters, persistent sessions,
cross-process transport, and sampling changes remain deferred.
