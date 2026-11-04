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

Resumed turns share one ended session anchor. Its duration does not measure chat length,
and its status does not summarize later failures. Inspect turn/workflow spans instead.
Sum native model-request input/output tokens, including retries; exclude agent aggregate
usage to avoid double counting. Missing usage remains unknown.

The [monitoring demo](../../homework/monitoring/README.md) adds user events and timing;
its README defines the fields and aggregation limits.

## Checks

```bash
uv run --locked python scripts/validate_logfire.py
# With telemetry credentials configured:
uv run --locked python scripts/validate_logfire.py --live
```

Offline mode uses in-memory export, scripted models, and a network guard. It checks
session/parent relationships, threads, tools, retries, cancellation, content policy,
and configuration reuse. Neither mode calls a live model or SEC.

Live mode also checks telemetry transport and returns trace/session IDs. Inspect the
trace in your Logfire project to confirm display and Agents-view grouping; the script
does not inspect the cloud UI. Ordinary automated tests disable export.

See the [decision record](../project/decisions/logfire_implementation_decisions.md).
Dashboards, alerts, persistent sessions, and cross-process transport remain deferred.
