# Connect the monitoring demo to live agents

Status: implemented. The prototype lives in `homework-monitoring`; it consumes the
shared [platform Logfire integration](logfire_implementation_plan.md).

## Agent and service integration

- Evidence Search reuses `CreditAssessmentAgent`, its scoped conversation memory,
  document service, and streaming events. Its new optional `document_tool_names`
  allowlist preserves existing callers' defaults; the demo enables only
  `list_documents` and `search_evidence`. Answers expose executed tools and citations.
- Credit Analysis uses a named PydanticAI coordinator with borrower discovery and a
  typed `run_credit_review` tool. Required borrower/dates/criteria come from analyst
  messages; missing or ambiguous details are requested in chat. Tools validate
  borrower and reporting-period availability, cutoff ordering, and nonblank criteria.
- The tool calls the existing assessment/review composition: SQLite financials,
  deterministic calculations and verification, requested ML, concurrent bullish and
  bearish agents, and final recommendation. Unspecified ML defaults to Logistic
  Regression and the coordinator is instructed to disclose that default.
- Completed structured reviews remain the evidence for follow-ups. Equal requests
  reuse the cached review; changed inputs or an explicit refresh can run a new one.
  Calculations and forecasts are never implemented in the coordinator.
- Runtime databases are isolated beneath ignored `homework-monitoring/runtime`.
  Business services and calculations retain ownership of their existing behavior.

## Chat feedback

- Every submitted question appears immediately, followed by an assistant message
  with live activity and streaming answer text. Submitted trigger values are consumed
  before reruns restore controls, preventing duplicate executions.
- Evidence events show actual model/tool progress. Native coordinator events show
  its tool dispatch and text. The assessment appears as one combined step; existing
  review callbacks report separate concurrent bullish/bearish and recommendation
  stages. No synthetic per-calculation progress or private reasoning is displayed.
- Activity and tool/source/result records persist with the message. Expandable
  sections show authoritative calculations, verification, ML, reviewer outputs,
  recommendation, limitations, and source records.
- Errors preserve available review results and completed activity, mark incomplete
  execution, and restore input controls. Cancellation and callback failure release
  session context. Streaming consumers retain `aclosing()`.

## Sessions and monitoring

- Startup loads repository `.env` and invokes the shared idempotent initializer.
  Missing model credentials disable chat with a setup message. UI status describes
  configuration rather than claiming confirmed cloud delivery.
- One retained `SessionContext` supplies both modes' session ID and trace. Every
  submitted question, including clarification, enters `session_scope()` and a
  `chat.interaction` span carrying mode, interaction ID, and final outcome.
- Native model/tool instrumentation and platform workflow spans retain parentage
  through worker-thread assessment and concurrent reviewers. No separate exporter,
  transcript logging, token counters, or per-question flushing is added.
- Reset closes conversations, clears both histories, cached reviews and drafts, and
  creates a new session context. Mode selection and exported telemetry are retained.
  Browser conversations are never shared through a resource cache.
- The styling, visible mode cards, Help, sample questions and monitoring-demo notice
  remain. All analysis inputs come from prompts; there is no required form.

## Validation and limits

- Offline tests cover streamed evidence with citations, tool allowlisting, full
  review/progress, clarification, validation, cached follow-ups, changed inputs,
  refresh, missing ML artifacts, failed reviewers, provider failure, cancellation,
  callback failure, UI reset, samples, rerun behavior, and browser isolation.
- A separate-process Logfire probe checks five turns across both modes retain one
  trace/session, actual tool → review → worker assessment/agent parentage, and a
  new trace after reset. Ordinary tests explicitly disable export. The existing
  shared offline fixture was already corrected to `false` when implementation began.
- The demo's tests are included in routine pytest and lint discovery and in
  `make test-offline`. Existing platform regression checks are run separately from
  live-provider smoke checks.
- Live smoke on 2026-10-25 completed evidence search, full SYN001 analysis with
  Logistic Regression, a follow-up with no tool calls, and a new-session clarification.
  The original session was `a91c63bc-4d28-4456-813a-9ff4b84c6ec9`; its trace was
  `01a172dc412ff844739c4f56fa10ffaa`. Reset produced a separate session and trace.
- Successful live model calls and locally captured trace relationships do not prove
  that a trace renders correctly in the Logfire UI. Manual Logfire UI/Agents-view
  inspection remains outstanding. A separate small transport check received HTTP
  **200** from the configured EU `/v1/traces` endpoint.
- Final offline regression run: **644 passed, 6 skipped**. The prototype contributes
  **19 passing tests**. Repository Ruff checks and changed-file formatting pass.

Authentication, durable chat recovery, custom analytics dashboards, production
hosting, and a public-news provider remain outside this demo. Runtime SQLite files
are retained for diagnostics; reset does not delete them.
