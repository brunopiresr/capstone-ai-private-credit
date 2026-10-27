# Logfire implementation decisions

Implementation reference: [Logfire implementation plan](../../archive/logfire_implementation_plan.md).
This record documents implementation choices and validation limits. It does not expand
the plan's scope.

## Scope and ownership

- The existing repository has no `TracingSession` implementation. The plan's instruction
  to replace it therefore means introducing the specified plain `SessionContext`; there
  is no existing root-span lifecycle to migrate.
- The central configuration module owns initialization, its process guard and lock,
  configuration status, content policy, and the span/no-op helper. The session module
  owns `SessionContext`, its context variable, and session propagation. The existing
  logging module owns console handlers, handler thresholds, and structured projections.
  The implementation uses `observability/configuration.py` and
  `observability/session.py` for those two modules.
- Entrypoints configure monitoring after loading their environment. Service factories,
  imports, domain models, calculations, and repository queries do not configure telemetry.
- Existing scheduling, graph traversal, validation, message history, calculation
  projections, retries, streaming event order, and public return values remain owned by
  their existing application components.

## Session and workflow rules

- A conversation retains the caller-supplied session, otherwise the active session,
  otherwise a newly generated session. It exposes a read-only session ID.
- Session propagation uses an ended anchor's SDK context carrier. No manually decoded
  trace IDs, retained root spans, counters, mutable session status, or token totals are
  added. A nested scope for the active session preserves the current parent.
- `_stream_question()` owns the session and turn scopes around execution and callbacks.
  `run_stream()` retains graph execution and only reads the active session ID for native
  PydanticAI invocation metadata. Internal async-generator consumers retain `aclosing()`.
  The event-printing adapter also closes closeable async iterators when callback handling
  fails; ordinary async iterables without `aclose()` retain their existing support.
- Full reviews establish their workflow before `asyncio.to_thread()`. Direct review of
  an existing assessment also establishes a session. Existing `asyncio.gather()` keeps
  bullish and bearish reviews concurrent, with recommendation afterward.
  Both public entrypoints delegate to the same private review implementation so a full
  review emits one `credit.review` workflow span instead of nested duplicate spans.
- Existing `log_step()` operation boundaries supply business spans. Native agent
  instrumentation owns model/tool execution and usage. Additional spans are limited to
  missing top-level assessment, review, and RAG workflows.
- Standalone narrative calls establish session context and rely on the named native
  `Assessment narrative` agent span. RAG owns a separate top-level `rag` workflow scope,
  including its empty-retrieval result. Extraction entrypoints establish session context
  for both populated and empty evidence; native extraction runs are named
  `Document extraction`.

## Logging and configuration rules

- Content capture defaults to disabled and accepts only whitespace-trimmed,
  case-insensitive `true` or `false`. Native instrumentation overrides reuse this policy.
- The SDK parses its standard settings. The application adds no separate cloud threshold
  parser, exporter, worker, OpenTelemetry imports, or OpenTelemetry dependency declarations.
- The named Logfire logging handler uses DEBUG and a null fallback. The package logger
  threshold is the lowest attached handler threshold, treating NOTSET as DEBUG and no
  handlers as INFO. Existing console formatting and external handlers are preserved.
- Monitoring remains opt-in through explicit configuration; uninitialized helper use is
  quiet. The SDK owns authentication and export behavior.
- CLI setup loads the repository `.env` with `override=False`, initializes monitoring,
  and uses bounded SDK flushing at shutdown. Notebook and Streamlit setup preserve their
  existing environment-loading behavior. No question-level flush or export worker is added.
- Handled failures log stable error codes/types without serializing arbitrary exception
  payloads. The final assessment log projects `issue_count` instead of issue strings,
  which may contain exception text; the returned assessment and its issues are unchanged.
- Standalone review-agent scope encloses its handled-failure logs as well as model
  execution so those logs retain the same session context.

## Validation scope

The user confirmed separate SDK acceptance validation while requesting tests for
application-owned auxiliary methods rather than Logfire itself. Unit tests use SDK
mocks/stubs for configuration, lazy session propagation, nested scope identity, and
cleanup. Scripted-model conversation tests cover retained session identity and cleanup.
Ordinary tests explicitly disable export, including when local SDK credentials exist;
Streamlit tests stub startup configuration to avoid changing process-global SDK state.

The initial carrier gate passed using Logfire's public `TestExporter` and
`SimpleSpanProcessor` testing utilities. Two native scripted-model agents ran in separate
event loops and turn scopes after the anchor ended; actual exported IDs confirmed one
shared trace and the expected anchor-to-turn-to-agent parents. The repository's
[SDK acceptance script](../../../scripts/validate_logfire.py) replaces that temporary gate and
extends coverage through the application entrypoints. It uses synthetic scripted models
and no live language-model or SEC requests.

### Offline acceptance evidence

On 2026-10-25, the implementation lead ran the final acceptance script successfully with
1,032 exported in-memory records. It checked five synchronous conversation turns sharing
one session and actual trace ID; actual parent relationships through tools, worker
threads, document processing, RAG, and credit review; and context restoration after
callback failures and cancellation. Explicit retry and peer-agent model requests totaled
33 input and 9 output tokens without double-counting aggregate agent usage. The private
content marker was absent. A network guard covering SDK configuration and execution
observed no connections during the offline run.

`make test-offline` passed with 625 tests passed and 6 skipped in 54.98 seconds.
`make lint` and `git diff --check` passed. Setup cells in all three changed notebooks
compiled successfully.

### Live synthetic smoke evidence

On 2026-10-25, the implementation lead ran the same synthetic acceptance scenario against
the configured EU project. Local exported-record assertions passed, and five telemetry
transport batches received successful 2xx responses. The run's identifiers are:

- Session: `6ad0a90b-97f9-41ce-af49-f48aaa27d07b`.
- Trace: `01a172b048ebe9255290ee844bbc0a27`.

This establishes live transport success separately from the offline hierarchy evidence.
The Logfire trace UI and Agents view were not inspected. Manual inspection of this trace's
displayed hierarchy and conversation grouping remains an outstanding acceptance check;
the delivery is not fully validated until that check is completed.

## Dependency resolution

The requested `logfire>=5.2,<6` range resolves to Logfire 5.3.0 in this environment.
Its `logfire-sdk` dependency requires `certifi>=2026.10.19`, so upgrading the previously
locked `certifi` 2026.2.25 is necessary to satisfy the new dependency. This transitive
upgrade is part of the Logfire change; unrelated dependency upgrades are excluded.

## Deferred work

HTTP instrumentation, query/transaction tracing, dashboards, alerts, sampling changes,
persistent sessions, cross-process transport, custom token counters, telemetry storage,
and a provider/plugin framework remain outside this implementation.
