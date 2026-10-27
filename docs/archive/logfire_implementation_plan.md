# Logfire monitoring plan using only Logfire APIs

> Historical record. Paths, APIs, commands, and line numbers below describe the original work. For the current layout and runnable commands, use the [documentation index](../README.md).

Status: architecture-reviewed implementation plan. The code examples below have not been
applied to the application; SDK runtime validation remains part of implementation.

## 1. Summary and design principles

Use Logfire's public APIs for configuration, instrumentation, spans, logging, and trace
context. Add the core `logfire>=5.2,<6` dependency; application code will have no direct
OpenTelemetry imports or additional OpenTelemetry dependency declarations.

**One conversation retains one session ID and one `trace_id` across every question and
workflow it triggers.** Questions and native agent/tool runs have nested spans; existing
operation boundaries supply business detail without tracing every function.

Cover conversations, credit reviews, document extraction and processing, RAG, and
deterministic assessments through existing entry points. UI changes remain deferred.

| Principle | Implementation choice |
|---|---|
| KISS | Save and reattach Logfire context between questions. Use ordinary spans around work; defer HTTP auto-instrumentation. |
| Separation of concerns | Keep configuration and session context in `observability`; preserve application scheduling, agent behavior, and calculation responsibilities. |
| Small and focused | Extend existing logging helpers and workflow boundaries. Add one small session data record. |
| DRY | Reuse native agent instrumentation, existing calculation projections, `log_step()`, and `log_event()`. |
| YAGNI | Avoid custom span lifecycles, exporters, token counters, telemetry storage, dashboards, and session persistence. Add further spans only for a demonstrated diagnostic gap. |

The session ID groups related runs in the Agents view; shared trace context puts them
in the same trace. Passing an identical `conversation_id` alone does not establish span
parentage. Validate actual trace IDs and parent IDs, not just correlation attributes.
[Conversation grouping](https://pydantic.dev/docs/logfire/observe/agents/)

### Architecture review and ownership rules

The context-carrier approach is supported by the SDK and addresses the single-trace
requirement without a retained root span or a custom lifecycle state machine. Validate it
against the acceptance checks below and keep the implementation within these boundaries:

- Configuration and the small configuration-status/span helper belong in one observability
  module; `SessionContext` and `session_scope()` belong in one session module. The existing
  logging module continues to own handlers, thresholds, and structured projections. Keep
  these dependencies acyclic; do not create a provider interface or plugin framework.
- Entry points initialize monitoring. Conversations retain session identity; application
  services own workflow scopes. Service factories must not configure global telemetry.
- Domain models, calculations, and repository queries do not import Logfire. Reuse their
  existing logging helpers rather than adding telemetry arguments to business methods.
- Each conversation retains one `SessionContext` for its lifetime, including Streamlit
  reruns. Initialize its carrier in the owning execution scope before concurrent fan-out;
  child agents inherit context without mutating session state. Arbitrary concurrent
  first-use of the same session from multiple OS threads is outside this delivery.
- SDK instrumentation owns model calls, tools, retries, timing, and token usage. Existing
  operation helpers own business spans. Do not add a second span for work already covered
  at the same boundary, or separately instrument the OpenAI SDK.

This is an integration with the existing application, not a new monitoring subsystem.

## 2. Central configuration

Initialize once after environment loading in CLI, notebooks, and web startup. Imports must
remain free of initialization side effects.

Document these settings:

```dotenv
LOGFIRE_TOKEN=
LOGFIRE_BASE_URL=https://logfire-eu.pydantic.dev
LOGFIRE_SERVICE_NAME=credit-monitoring
LOGFIRE_ENVIRONMENT=development
LOGFIRE_SEND_TO_LOGFIRE=if-token-present

# Application setting controlling messages and tool contents.
LOGFIRE_CAPTURE_CONTENT=false
LOGFIRE_MIN_LEVEL=info
```

Use the existing project's credential with permission to send telemetry. Keep credentials
outside source control and ignore `.logfire/`.
[Credential documentation](https://pydantic.dev/docs/logfire/manage/use-api-keys/)

The central initializer will perform these operations:

```python
logfire.configure(
    send_to_logfire=(
        None
        if "LOGFIRE_SEND_TO_LOGFIRE" in os.environ
        else "if-token-present"
    ),
    service_name=os.getenv(
        "LOGFIRE_SERVICE_NAME", "credit-monitoring"
    ),
    console=False,
)

logfire.instrument_pydantic_ai(
    include_content=capture_content,
    include_binary_content=False,
)
```

Protect initialization with a simple process-level guard and lock to handle repeated
notebook calls and Streamlit startup. Resolve `capture_content` once from the application
setting, defaulting to `false`, and report invalid values as configuration errors. Mark
setup complete only after successful initialization. Let the SDK parse its standard
environment settings, including `LOGFIRE_MIN_LEVEL`, rather than duplicating that parser.

Attach one named `LogfireLoggingHandler` to the `credit_monitoring` logger. Preserve the
existing console handler and calculate the package logger's threshold from its handlers
so cloud DEBUG can coexist with console WARNING. Put this threshold calculation in one
shared helper called after either handler changes; handle `NOTSET` deliberately. Use a
null fallback for the Logfire handler to avoid duplicate stderr output during SDK
suppression. Keep console formatting and external handlers intact.
[Standard logging integration](https://pydantic.dev/docs/logfire/integrations/logging/logging/)

Missing credentials or explicitly disabled export must leave offline workflows usable
without authentication prompts. SDK configuration and transport behavior remain Logfire's
responsibility.
[Configuration documentation](https://pydantic.dev/docs/logfire/manage/configuration/)

`if-token-present` may also discover credentials stored locally by Logfire. Tests must
explicitly disable export even when no environment token is set. Add explicit repository
`.env` loading in the assessment CLI before monitoring setup, with `override=False` so
exported environment variables retain precedence. Preserve the existing environment-loading
behavior in notebooks and Streamlit.

## 3. Session context and agent instrumentation

Replace `TracingSession` with a plain `SessionContext` containing only:

- A generated session ID.
- A Logfire context carrier, populated on first use.

Remove manually managed root spans, activation counters, deferred span closure, and custom
trace-ID extraction.

Create a short session anchor in a fresh trace and capture its context. Reattach that
context for each turn. Logfire documents continuing a trace after the original parent
span has ended.
[Context propagation](https://pydantic.dev/docs/logfire/instrument/python/distributed-tracing/)
The tracing specification explicitly permits using an ended span as a parent. This is
context propagation, not a fabricated trace ID or a custom exporter.
[Span end semantics](https://opentelemetry.io/docs/specs/otel/trace/api/#end)

Representative implementation:

```python
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

import logfire


@dataclass
class SessionContext:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    carrier: dict[str, str] | None = None


_current_session: ContextVar[SessionContext | None] = ContextVar(
    "credit_monitoring_session", default=None
)


@logfire.instrument(
    "agent.session",
    new_trace=True,
    extract_args=False,
)
def _capture_session_trace():
    return logfire.get_context()


@contextmanager
def session_scope(session=None):
    current = _current_session.get()

    # Preserve the current parent span during nested service calls.
    if current is not None and (
        session is None or session is current
    ):
        yield current
        return

    session = session or SessionContext()
    token = _current_session.set(session)
    try:
        if not is_observability_configured():
            yield session
            return

        attributes = {
            "gen_ai.conversation.id": session.session_id,
        }
        with logfire.set_baggage(**attributes):
            if session.carrier is None:
                session.carrier = _capture_session_trace()

            with logfire.attach_context(session.carrier):
                yield session
    finally:
        _current_session.reset(token)
```

`new_trace=True` ensures independent sessions receive independent traces, including when
another trace is active. It is a documented Logfire option.
[Instrumentation API](https://pydantic.dev/docs/logfire/api/logfire/#logfire.Logfire.instrument)

Apply these integration rules:

- Each conversation retains a `SessionContext`; accept an optional caller-supplied
  `session` in `start_conversation()`.
- Expose a read-only `session_id`.
- Standalone workflows use `session_scope()` to create a session or reuse the active one.
- Existing conversation close commands retain their current behavior. There is no
  telemetry span requiring manual closure between questions.
- Pass the session ID as `conversation_id` to every PydanticAI invocation, including
  extraction and independent review agents.
- Keep each agent's message history independent.
- Change the assessment agent's tracing default to inherit central configuration.
  Preserve explicit overrides and remove review agents' unconditional instrumentation
  disablement. An explicit tracing opt-in must reuse the central content policy rather
  than enabling prompt/tool content independently.
- Name extraction and narrative agents explicitly.

The following illustrates the required nesting. In the implementation, `_stream_question()`
owns the session/turn scopes and `run_stream()` retains the `agent.iter()` call; do not
move graph traversal or duplicate the scopes:

```python
with session_scope(conversation_session) as session:
    with logfire.span("agent.turn"):
        async with agent.iter(
            prompt,
            message_history=history,
            conversation_id=session.session_id,
            usage_limits=usage_limits,
        ) as run:
            # Retain existing graph traversal and validation.
            ...
```

Logfire's native PydanticAI integration captures available messages, tool arguments/results,
retries, timing, exceptions, and provider-reported usage.
[PydanticAI integration](https://pydantic.dev/docs/logfire/integrations/llms/pydanticai/)

The anchor span ends after context capture. **Its duration does not represent the
conversation's elapsed time.** Turn and workflow spans provide execution timings while
all activity remains in the same trace. The anchor's status also does not summarize later
failures: inspect turn/workflow statuses. Do not add a mutable session-status aggregator.
Keep default sampling for this delivery; evaluating sampling across a trace resumed after
idle periods is a separate requirement.

## 4. Workflow spans, logs, errors, and usage

Start the review scope before dispatching synchronous assessment work:

```python
with (
    session_scope(),
    logfire.span(
        "credit.review",
        borrower_id=borrower_id,
    ),
):
    assessment = await asyncio.to_thread(
        self.assessment_service.assess,
        borrower_id,
        period_end,
        information_cutoff,
        ml_enabled=ml_enabled,
    )

    return await self.review_assessment_async(
        assessment,
        decision_context=decision_context,
    )
```

Retain `asyncio.gather()` for bullish and bearish agents. Their spans remain siblings
beneath the review workflow; recommendation runs afterward in the same trace.

Use normal task context propagation through `asyncio.gather()` and `asyncio.to_thread()`.
Manual context reattachment is needed between conversation turns, where the previous
execution scope has ended.
[Python task and thread context](https://docs.python.org/3.14/library/asyncio-task.html)

Direct calls to `review_assessment_async()` also establish or reuse a session. Child
services reuse the active parent rather than reattaching the session anchor, which would
flatten the span tree. Keep scheduling, retries, validation, and result construction in
their current owners.

Extend the existing `log_step()` helper to wrap its timing and progress records in a
Logfire span:

```python
span_context = (
    logfire.span(
        action,
        **_snapshot({**_context.get(), **context}),
    )
    if is_observability_configured()
    else nullcontext()
)

with span_context:
    # Preserve existing start, completion, failure,
    # and elapsed-time records.
    ...
```

Inspect the coverage gained from `log_step()` before adding more spans. It already wraps
covenant resolution/calculation, feature building, document processing, section extraction,
cache operations, and ingestion steps. Add only missing top-level assessment, review, and
RAG boundaries needed to make their workflows visible. Native named agent spans identify
review and narrative runs without an additional wrapper for each agent.

Use stable operation names and existing business identifiers as attributes. Do not embed
borrower IDs or document names in span names. Defer HTTP auto-instrumentation, query or
transaction tracing, layer/execution-mode labels, worker identifiers, and blanket spans
for every stage until a specific diagnostic question requires them. Do not rewrite queries
or add calculation-level telemetry imports to improve tracing coverage.

Keep uninitialized library usage quiet through the centralized span/no-op helper. The
direct Logfire snippets here assume startup has already configured monitoring.

Retain existing calculation projections:

```python
log_event(
    logger,
    "calculate_covenant",
    inputs=calculation_inputs(resolution, financials),
    outputs=covenant_output(result),
)
```

Preserve existing INFO outcomes and DEBUG diagnostics. Add a new record only when it
explains a decision that current records and spans cannot explain. Avoid serializing
complete domain objects or duplicating transcripts into application logs.

Record exceptions where handlers convert failures into application results:

```python
except Exception as error:
    logger.exception(
        "Credit review agent failed",
        extra={
            "role": self.role,
            "error_code": _error_code(error),
        },
    )
    # Preserve the existing failed execution result.
```

Let spans record escaping exceptions. Record handled stage failures explicitly, use
warnings for expected invalid arguments, and preserve cancellation propagation.

Retain `aclosing()` throughout streaming consumers so interrupted streams close their
spans and restore context in the consuming task. Do not introduce queues or background
producers or decorate yielding generators with `logfire.instrument()`. Prefer placing
scopes around stream consumption; where the existing async-generator API requires a
scope inside a generator, document `aclosing()` for direct consumers and retain explicit
cleanup at every internal consumption boundary.
[Generator guidance](https://pydantic.dev/docs/logfire/reference/generators/)

For tokens:

- Use native `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` on model-request
  spans.
- Calculate session totals from those request spans, including retries and nested agents.
- Avoid adding agent aggregate fields to request totals.
- Preserve available cache/reasoning details; unavailable usage remains unknown.
- Do not add mutable application token counters.
  [Usage conventions](https://pydantic.dev/docs/ai/integrations/logfire/#aggregated-usage-attribute-names)

Keep secret scrubbing enabled and content capture configurable, with content disabled by
default. Logfire excludes LLM message bodies from automatic scrubbing. Disabling native
content capture does not sanitize custom application logs: keep their explicit projections
and avoid logging complete prompts, document text, or arbitrary exception payloads.
[Scrubbing behavior](https://pydantic.dev/docs/logfire/instrument/python/scrubbing/)

## 5. Validation and delivery

Use Logfire's in-memory testing utilities and scripted models. Explicitly disable network
export during ordinary tests. Inspect exported records through Logfire's testing API
without direct OpenTelemetry imports. Restore process-global instrumentation and handlers
between tests. Assert application-owned behavior and parent relationships rather than
complete SDK span snapshots.
[Testing documentation](https://pydantic.dev/docs/logfire/reference/testing/)

Acceptance checks:

- Five questions share one session ID and `trace_id`, including synchronous questions
  using separate event loops.
- All nested agents, tools, calculations, worker-thread operations, and review stages
  retain correct parent relationships.
- Nested session scopes preserve their current parent; independent sessions remain
  isolated.
- Creating a new session while another trace is active gives it an independent trace;
  resuming an existing session preserves its trace ID. Repeated Streamlit-style calls
  leave no session context active while idle.
- The session anchor is emitted once; turn/workflow spans remain descendants even though
  it has ended. Its duration/status is not treated as conversation duration/status.
- Context is restored after success, failure, cancellation, callback errors, and
  interrupted streams.
- Conversation closure remains idempotent and requires no telemetry lifecycle
  bookkeeping.
- Token totals include retries and multiple agents without double-counting.
- Initialization and handler registration remain idempotent.
- Disabled export performs no network writes.
- Disabled content capture preserves metadata and usage.
- Console verbosity and CLI JSON output retain their existing behavior.

Deliver in three focused steps, all required for the stated outcome:

1. Add the core dependency, explicit configuration, logging bridge, and `log_step()` spans.
2. Add session context and agent/workflow integration, preserving existing public behavior.
3. Complete offline telemetry checks, existing regression tests, setup examples, and the
   synthetic smoke run.

During implementation, run the relevant observability, conversation/streaming, and review
tests, then the existing offline suite and lint checks. The session context snippet is
checked for Python syntax during this review; SDK runtime verification remains part of
implementation because Logfire is not yet installed. A syntax check does not establish
correct context parenting.

After credential configuration, run a small synthetic smoke scenario against the EU
project and verify conversation grouping, nesting, errors, and token usage. Update setup
instructions and examples, using SDK background export and bounded flushing at CLI
shutdown. Do not flush after each question or add a custom export worker. Keep dashboards,
alerts, sampling customization, cross-process session transport, and persistent session
recovery outside this delivery.

## 6. Coding-agent implementation contract

These decisions make the preceding design concrete. Preserve the single-trace requirement
and all deferred scope while implementing the following interfaces and defaults.

### Public API and session ownership

- Export `configure_observability()`, `SessionContext`, and `session_scope()` from
  `credit_monitoring.observability`. Importing the package must not initialize monitoring.
- Add optional `session: SessionContext | None = None` to `start_conversation()` and the
  conversation constructor. Resolve the retained session in this order: explicitly
  supplied session, active session, new `SessionContext`.
- Retain that object across questions and Streamlit reruns. Expose read-only
  `conversation.session_id`; keep the carrier as internal propagation state. Do not add
  a public trace-ID parser or manually decode `traceparent`.
- Provide an internal active-session accessor for execution adapters. Keep the existing
  public `ask()`, `ask_async()`, and streaming signatures unchanged.
- Conversation closure continues to discard history and reject later questions. The
  completed anchor requires no additional cleanup, including for caller-supplied sessions.

### Exact integration boundaries

- Add an optional private session parameter to `_stream_question()`. Conversation calls
  pass their retained session; single-question calls reuse an active session or create one.
  After existing input validation, activate the session and open `agent.turn` around both
  execution and event callbacks.
- In `run_stream()`, read the active session ID and pass it to `agent.iter()` as
  `conversation_id`. Do not open another session or turn span there. Preserve existing
  graph traversal, usage limits, event order, validation, and history commits.
- Establish or reuse `session_scope()` at standalone assessment, review, document-processing,
  extraction, and RAG/narrative entry points, including synchronous and asynchronous
  variants. Cover both direct review-of-assessment calls and full review calls, and both
  individual-document and batch processing. Nested scopes preserve the current parent.
- Pass the active session ID into every native agent invocation, including extraction
  `run_sync()`, narrative `run()`/`run_sync()`, and review `iter()` calls. Use stable agent
  names: `Document extraction` and `Assessment narrative`; preserve existing assessment
  and review names.
- Retain `aclosing()` at every internal stream-consumption boundary and document the same
  requirement for direct consumers. Cleanup must run in the consuming task before leaving
  its session/turn scopes.

### Configuration and logging defaults

- Parse `LOGFIRE_CAPTURE_CONTENT` once after trimming whitespace and lowercasing. Accept
  only `true` and `false`, default to `false`, and raise a useful configuration error for
  any other value.
- Name the package handler `credit_monitoring_logfire`, set its level to `logging.DEBUG`,
  and use `logging.NullHandler()` as its fallback. Let the SDK's `LOGFIRE_MIN_LEVEL` apply
  the final cloud threshold; do not add another application-level cloud threshold parser.
- After either application handler changes, set the package logger to the lowest attached
  handler threshold, treating `NOTSET` as `DEBUG` and using `INFO` if no handlers exist.
  Keep package propagation disabled and preserve console formatting and external handlers.
- Set the assessment facade's `tracing_enabled` default to `None`: `None` inherits central
  native instrumentation, `False` disables native instrumentation for that agent, and
  `True` uses the central content policy. Workflow spans remain independently controlled.
- Before initialization, application span/session helpers perform no tracing and emit no
  SDK configuration warnings. Do not change application return values based on telemetry
  availability.

### Implementation order and acceptance gate

1. Add the core dependency and update the lockfile without unrelated upgrades. Before
   broad integration, prove the carrier approach using in-memory SDK export: create one
   anchor, let it end, run two native agents in separate scopes using its carrier, and
   assert that their actual trace IDs match the anchor and their parents are correct.
2. Implement configuration, the logging bridge, conversation integration, and the remaining
   workflow boundaries. Complete the acceptance checks in section 5 using scripted models
   and explicitly disabled network export. Restore global handlers/instrumentation between
   tests.
3. Run the focused observability, conversation/streaming, and review tests, then `make lint`
   and `make test-offline`. Perform the synthetic live smoke run only after local credential
   configuration, and inspect the exported hierarchy rather than just conversation IDs.

### Completion report

Report the changed interfaces, checks run and their outcomes, and any incomplete acceptance
checks. Distinguish offline test results from the live smoke result. If credentials are
unavailable, report the smoke run as outstanding; do not treat it as passed or consider
the delivery fully validated. Keep all previously deferred instrumentation and infrastructure
outside this implementation.
