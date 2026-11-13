# Logfire setup and validation

Logfire provides optional workflow traces, native PydanticAI activity, and usage.
Entry points initialize it after loading the environment; imports do not.

## Configure

Copy [.env.example](../../.env.example) to `.env` and set your project's send credential
and matching region URL. For an EU project:

```dotenv
LOGFIRE_TOKEN=
LOGFIRE_BASE_URL=https://logfire-eu.pydantic.dev
LOGFIRE_SERVICE_NAME=credit-monitoring
LOGFIRE_ENVIRONMENT=development
LOGFIRE_SEND_TO_LOGFIRE=if-token-present
LOGFIRE_CAPTURE_CONTENT=false
LOGFIRE_MIN_LEVEL=info
```

Keep `.env` and `.logfire/` out of Git. `if-token-present` can use locally stored SDK
credentials. Set `LOGFIRE_SEND_TO_LOGFIRE=false` to disable export explicitly.
Exported environment variables take priority over `.env`.

Content capture defaults to false in the application; `.env.example` enables it.
Set it explicitly to `true` or `false`. Enabling it sends native model content and
supported question/comment text. Session names remain explicit
metadata regardless of this setting. Application logs have their own projections;
keep SDK secret scrubbing enabled.

Cloud verbosity uses `LOGFIRE_MIN_LEVEL`; console verbosity uses `configure_logging()`
or the CLI's `--log-level`. CLI stdout remains assessment JSON.

## Sessions

For library use, call `configure_observability()` from `credit_monitoring.observability`
after loading your environment. Pass `SessionContext(name="Quarterly review")` to
`agent.start_conversation(...)`, or group service calls with `session_scope(...)`.
Use async conversation methods in an active event loop.

Conversation scopes carry identity without creating or resuming a root span. Independent
turns and workflows start separate traces; nested operations remain children of the
operation that called them. Inspect turn/workflow spans for duration and outcome.

Web entrypoints, callbacks, and independently rerun fragments bind a shared `session.id`
UUID from Streamlit session state. It survives navigation, borrower changes, reruns, and
chat clears. A new Streamlit session gets a new UUID; this is not a persistent browser
cookie or cross-tab identity. `gen_ai.conversation.id` continues to identify each agent
conversation, and existing conversation cost queries work across its separate traces.

To retrieve all exported application logs and spans for a web session, copy `session.id`
from any of its records and filter by that attribute in Logfire, or use SQL:

```sql
SELECT start_timestamp, kind, span_name, trace_id, span_id, attributes
FROM records
WHERE attributes->>'session.id' = '<web-session-uuid>'
ORDER BY start_timestamp;
```

Choose the relevant time range, service, and environment. Records emitted before a web
session exists are process-level records. The identifier is preserved through a narrow
UUID-only scrub callback; other sensitive fields retain default scrubbing.

Sum native model-request input/output tokens, including retries; exclude agent aggregate
usage to avoid double counting. Missing usage remains unknown.

The [monitoring demo](../../homework/monitoring/README.md) adds user events and timing;
its README defines the fields and aggregation limits.

## V2 response feedback

Both V2 assistants support one thumbs rating and one separate detailed review per
response. Detailed reviews require a 1–5 score and category (including **Helpful**);
the message is optional and limited to 2,000 characters. Submitted controls stay
disabled for the current chat transcript. Clearing the chat removes that local state.

Feedback uses Logfire's
[end-user evaluation events](https://pydantic.dev/docs/logfire/evaluate/live-evals/#record-end-user-feedback):
`gen_ai.evaluation.result`, named `user_helpfulness` (0/1) or `user_review_score` (1–5).
The original response's saved context links each event to its completed agent span.
Rule-based answers use a separate `Structured fallback` target and response span;
plain errors and status messages have no rating controls.

Events include `interaction_id`, `feedback_id`, `session.id`, assessment and borrower
IDs, dates, persona (`mode`), response origin, and model/conversation IDs when available.
Written review messages are always included, even with `LOGFIRE_CAPTURE_CONTENT=false`;
model prompts and responses still follow that setting. Default SDK scrubbing remains
enabled. Delivery uses normal asynchronous telemetry export, with no durable queue or
application retries. The UI acknowledges submission without confirming cloud storage.

In Logfire, open **Evals: Live Monitoring** and select **Credit assessment agent** or
**Structured fallback**. For individual submissions, filter records by
`attributes->>'event_name' = 'user.feedback'` and optionally by `feedback_type` (`quick`
or `review`), `interaction_id`, or `session.id`. Open the event's trace to inspect the
original response. For example:

```sql
SELECT start_timestamp, trace_id, span_id, attributes
FROM records
WHERE attributes->>'event_name' = 'user.feedback'
ORDER BY start_timestamp DESC;
```

## Checks

```bash
uv run --locked python scripts/validate_logfire.py
# With telemetry credentials configured:
uv run --locked python scripts/validate_logfire.py --live
```

Offline mode uses in-memory export, scripted models, and a network guard. It checks
session/parent relationships, threads, tools, retries, cancellation, content policy,
and configuration reuse. Neither mode calls a live model or SEC.

Live mode also checks telemetry transport and returns conversation/web-session IDs and
the five turn trace IDs. Inspect the traces in your Logfire project to confirm display,
filtering by `session.id`, and Agents-view conversation grouping; the script
does not inspect the cloud UI. Ordinary automated tests disable export.

See the [decision record](../project/decisions/logfire_implementation_decisions.md).
Dashboards, alerts, persistent sessions, and cross-process transport remain deferred.
