# Deferred POC simplification plan

Prepared 27 October 2026 after the structural cleanup and targeted backend reduction.
This is an implementation plan for follow-up work; none of the seven changes below
is claimed complete. Keep all current features until the indicated product or
compatibility decision is resolved. UI behavior/design is deferred until the UI is stable.

The [complexity review](../reviews/poc_simplification_review.md) records completed
changes and ranks the remaining work. [Architecture](architecture.md) and the
[guides](../README.md#usage-guides) remain the current behavior references.

## 1. Remote cost reconciliation and polling

**Evidence and cost.** [costs.py:93](../../src/credit_monitoring/observability/costs.py#L93)
builds remote telemetry SQL; lines 130 and 152 duplicate synchronous/asynchronous
pagination. [cost_footer.py:12](../../src/credit_monitoring/web/cost_footer.py#L12)
adds six retry times, cached snapshots, stale state, Retry-After handling, and a timed
Streamlit fragment. Readers must understand a remote reconciliation subsystem before
explaining a small cost footer.

**Recommended change.** First factor common query options, row accumulation, and
summary/error classification behind the existing public methods, with one sync and
one async I/O loop. After UI stabilization, replace automatic retry scheduling with
one explicit refresh per analyst request if the monitoring lesson does not require
automatic delayed-export reconciliation. Keep a last successful snapshot with its
query time and explicit stale/partial/unavailable status. Do not substitute a local
estimate for telemetry-derived cost.

**Retained behavior and interfaces.** Preserve session/service/environment scope,
pagination, duplicate-span handling, request/cached-token accounting, known-price
checks, and sanitized missing-token/query-error states. Keep
`get_session_cost()`/`get_session_cost_async()` signatures and summary fields in the
first pass. No data migration is required. Removing automatic polling changes visible
refresh behavior and therefore needs a separate UI decision.

**Steps and acceptance.** Lock existing query/summary fixtures, extract pure helpers,
then simplify UI state only after the refresh decision. Run observability cost/pricing
and footer refresh tests, including multiple pages, duplicate spans, unsupported
pricing, partial data, disabled export, missing read token, Retry-After, and a new
session. Assert that refresh never invokes an agent/tool, changes conversation history,
or requests data for another session. If polling stays, preserve bounded retries.
A live remote check is a separate credentialed validation; offline fakes are sufficient
for the refactor. Estimate: 1–2 days; medium risk.

## 2. Structured-answer and plain-text streaming lifecycle

**Evidence and cost.** [streaming.py:40](../../src/credit_monitoring/agents/streaming.py#L40)
and line 145 adapt structured output with graph validation, tool events, and retry
handling. [monitoring_backend.py:298](../../homework/monitoring/monitoring_backend.py#L298)
implements a second loop for plain-text credit-chat output, tool events, and history.
[conversation.py:105](../../src/credit_monitoring/agents/conversation.py#L105) adds
conversation-owned lifecycle and early-close handling. Some duplication reflects
real differences between validated final-result tools and text deltas.

**Recommended change.** Keep separate small output adapters for `AnswerContent`
snapshots and text deltas. Extract only shared tool-event translation, terminal error
classification, and successful-history commit rules when the tests demonstrate the
same contract. Prefer functions and explicit state over a strategy/class hierarchy.
Do not force the monitoring chat into the typed answer schema or expose provisional
output as a completed answer merely to unify code.

**Retained behavior and interfaces.** Preserve `AgentEvent` kinds, real tool traces,
bounded tool/model rounds, source scope, callbacks, sanitized failures, and existing
sync/async conversation entrypoints. Only graph success commits successful history;
cancellation/early close must not retain unfinished tool sequences. Preserve plain-text
UI output, confidence/explanation on typed answers, content-capture settings, session
trace identity, and reuse of completed review results. No persisted data migration.

**Steps and acceptance.** Before extraction, add/retain paired lifecycle tests for
both adapters: normal completion, multi-tool turn, invalid output plus repair,
request failure, tool failure, usage limit, cancellation, consumer early close,
failed callback, and five sequential follow-ups. Exercise real PydanticAI scripted
streams, not snapshots mirroring helper code. Run agent streaming/conversation and
monitoring backend/telemetry tests. Wait for stable UI event requirements; choose
which output differences remain before introducing a shared helper. Estimate: 2–3
days; high regression risk relative to the line-count gain.

## 3. Mock portfolio and working assessment presentation

**Evidence and cost.** [demo_assessment_service.py:52](../../src/credit_monitoring/application/demo_assessment_service.py#L52)
loads fixed expected cases; [benchmark.py:19](../../src/credit_monitoring/web/benchmark.py#L19)
renders a mock portfolio. [workspace.py:24](../../src/credit_monitoring/web/workspace.py#L24)
and the working assessment page use actual deterministic services. Two representations
of borrower status, trends, facts, and actions increase reader effort and maintenance.

**Recommended change after UI stabilization.** Keep both existing entrypoints initially.
Extract only proven-identical formatting helpers. Then choose either to retain the
mock as an explicitly labeled demonstration under homework, or to replace its data
assembly with actual service results. The latter needs a deliberate definition of
portfolio aggregation; there is no existing aggregate WATCH policy to infer. Do not
quietly reinterpret fixed expected labels as computed runtime outputs.

**Retained behavior and interfaces.** The working assessment must retain exact individual
covenant statuses, financial inputs, headroom, provenance, trends, verification, optional
ML failures, selected dates, session isolation, and explicit run action. If the mock
stays, retain its label, evaluation-data path, and prefill behavior. The current cleanup
changes only paths and preserves the UI.

**Steps and acceptance.** Decide the mock's destination and whether computed portfolio
aggregation is required. Capture current working and mock behavior using existing
Streamlit tests. Consolidate display helpers only after checking status semantics.
If moving the mock, update navigation, imports, and prefill tests together; if computing
a portfolio, specify aggregate statuses and missing-period behavior first. Test no-key
startup, gold-label absence from working inputs, unchanged selected dates, explicit
rerun behavior, and model failure without loss of deterministic results. No automatic
delete of evaluation labels is permitted. Estimate: 1–3 days after the product decision;
UI work remains out of the present cleanup.

## 4. Multi-agent credit review and future news abstraction

**Evidence and cost.** [credit_review_service.py:119](../../src/credit_monitoring/application/credit_review_service.py#L119)
composes three agents, progress, news, failures, deferral, and sync/async wrappers;
line 226 schedules independent reviewers. [credit_review.py:70](../../src/credit_monitoring/agents/credit_review.py#L70)
introduces shared agent base classes. [public_context/retrieval.py:9](../../src/credit_monitoring/public_context/retrieval.py#L9)
defines a provider protocol and unavailable implementation without a live provider.
This is implemented functionality with speculative extension surface around it.

**Recommended change.** Retain bullish/bearish/recommendation roles and their complete
rationale handoff. Replace inheritance that only supplies fixed role configuration
with a small common role-running function and explicit role prompts, if it reduces
branching. Retain a thin public facade for existing service callers. Unless live news
is an imminent requirement, replace the provider protocol with an optional explicit
`PublicNewsContext` input or one injected async loader callable; default to unavailable.
Do not build a new orchestration framework.

**Retained behavior and interfaces.** Preserve single-borrower/cutoff scope, immutable
sanitized evidence, independent parallel perspectives, full arguments/counterevidence,
argument-ID judgments, analyst advisory actions, verification blocking, explicit
news/ML gaps, timeouts/retries, partial failure deferral, and cancellation. Keep
`review*` and `review_assessment*` signatures until callers and fixtures migrate. Any
news-input replacement is a Python API change affecting bootstrap, monitoring backend,
and tests; provide one atomic internal migration, not two permanent interfaces.

**Steps and acceptance.** Confirm that no live provider or external caller depends on
the protocol; choose explicit context versus callable based on whether asynchronous
collection is actually required. Simplify role execution first, then news wiring.
Retain public domain result shapes and saved evaluation captures. Run scripted review
and monitoring tests for concurrent perspectives, complete handoff, invalid references,
one/both reviewers failing, synthesis failure, blocked verification, no news, future
news rejection, timeout, and cancellation. Live qualitative review is separate from
code refactoring and must not be reported as proven by mocks. Estimate: 2–4 days;
medium/high risk; news API decision required.

## 5. Unimplemented prediction fields and persisted contracts

**Evidence and cost.** [risk_prediction.py:46](../../src/credit_monitoring/domain/risk_prediction.py#L46)
defines deterioration probability, anomaly score, risk levels, and drivers. The built-in
logistic adapter at [logistic_model.py:65](../../src/credit_monitoring/ml/logistic_model.py#L65)
produces next-quarter breach probability only. Speculative fields propagate into
[analytics_schema.sql:62](../../src/credit_monitoring/persistence/analytics_schema.sql#L62),
repository serialization, evidence sanitization, stub validation, and tests.

**Recommended change.** Narrow the active model output to the implemented breach
probability, status, target/horizon, identifiers, artifact identity, generated time,
and error. Remove unsupported fields only after choosing how to treat old local
analytics databases and captured JSON. Do not invent new model outputs to justify
existing columns.

**Retained behavior and interfaces.** Preserve null versus zero, probability bounds,
stub honesty, missing-current-input abstention, model-failure isolation, borrower/date
identity, snapshot linkage, and synthetic-training disclosure. Shared feature columns,
training labels, the model manifest, and artifact bytes need no change for output-only
field removal. Removing fields is a Python/JSON/SQLite contract change.

**Steps and data handling.** Inventory old prediction rows and saved captures first.
Preferred POC policy: preserve historical files as read-only evidence, create fresh
runtime databases, and document the old/new output shapes; do not rewrite archived
captures. If runtime continuity is required, implement a single explicit migration
that copies retained columns transactionally and verifies row counts/foreign keys.
Update domain model, DDL, repositories, verifiers, review evidence, docs, and test
models in one change. Use explicit legacy-capture parsing only for genuine consumers.

**Acceptance.** Round-trip current prediction rows; reject invalid probability and
scope; verify stub/failure outputs cannot provide forecasts; load old evidence without
mutating it; preserve deterministic assessments when prediction/storage fails; verify
model artifact compatibility and feature order remain unchanged. Decide fresh-state
versus migration before implementation. Estimate: 1–2 days with fresh runtime state,
2–3 with a migration; medium compatibility risk.

## 6. Ingestion namespace depth

**Evidence and cost.** `ingestion/cleaners/`, `converters/`, and `loaders/` mostly contain
single modules. The substantive entrypoints are [clean_html:31](../../src/credit_monitoring/ingestion/cleaners/sec_html.py#L31),
[load_markdown:16](../../src/credit_monitoring/ingestion/converters/sec_markdown.py#L16),
and [load_sec_html:27](../../src/credit_monitoring/ingestion/loaders/sec.py#L27).
The extra nesting suggests more independently extensible implementations than exist.

**Recommended change.** Use direct modules under ingestion: `sec.py` for download/catalog
records, `sec_html.py` for cleanup/conversion, `financials.py` for CSV loading, and
retain distinct `sections.py`/`evidence.py` modules for complete-document segmentation
and selected excerpts. Keep modules cohesive rather than forcing everything into one
large file. Remove empty old namespaces after all imports and commands migrate.

**Retained behavior and interfaces.** Function signatures remain unchanged. Public module
imports and the financial loader's `python -m` entrypoint move; update scripts, notebooks,
fixtures, service composition, guides, and commands atomically. This is a checkout-based
POC, so temporary legacy-import shims are unnecessary unless an external caller is
identified. Cached file formats, conversion version, extraction configuration, and
source offsets stay identical. No cache invalidation or redownload should result from
an import move alone.

**Steps and acceptance.** Search all imports and executable notebook cells; move modules,
update imports and CLI examples, then remove empty packages. Run download/import/help
checks, cache reuse and failed-publication tests, substantive HTML preservation,
conversion markers, full-section coverage, quote offsets, retrieval scope, notebook
controlled cells, and CLI loader tests. Check source/cache hashes before and after.
No UI change or model request is required. Estimate: half to one day; low/medium
risk, lower benefit than the completed service simplifications.

## 7. Three overlapping evaluation approaches

**Evidence and cost.** [agent-tests/criteria_helpers.py:59](../../homework/agent-tests/criteria_helpers.py#L59)
uses a direct structured PydanticAI judge; [llm-judges/evaluator.py:55](../../homework/llm-judges/src/credit_monitoring_judges/evaluator.py#L55)
uses Evidently; the dated [workbench.py:1](../../homework/evaluation/2026-10-26/workbench.py#L1)
captures answers, business labels, judge results, and summaries. Capture formats,
missing-data policies, reports, and result categories overlap. Evidently's Python
3.13 environment is a real compatibility boundary, not arbitrary duplication.

**Recommended change.** Retain assignment artifacts, historical results, and environment
separation. Select the dated runner as the default exploratory evaluation walkthrough
if the course does not require another canonical path; keep direct criteria tests as
small executable acceptance scenarios and Evidently as an optional adapter/lesson.
Share pure snapshot serialization and label/report formatting only where semantics
match. Avoid a general evaluator registry or plugin framework.

**Retained behavior and interfaces.** Preserve generating/judge model identity, exact
ordered executed tool trace, complete-answer requirements, explicit missing evidence,
rubric versions, case IDs, response hashes, and held-out split boundaries. Manual/business
labels must never enter judge prompts. New runs must not overwrite old evidence.
Deterministic financial/SEC comparison remains a separate quality check; do not merge
its exact numeric result into an LLM judge's opinion. Keep live runs opt-in.

**Steps and data handling.** Inventory capture/result contracts and coursework requirements;
choose the canonical walkthrough. Define a minimal common captured-case record only
for fields all consumers actually need, with adapters for legacy captures rather than
rewriting history. Move shared pure helpers outside the Python-3.13-only package and
keep dependency imports optional. Update guides and Make targets. Test incomplete
runs, missing/reordered criteria feedback, input size limits, absent sources, label
leakage, stable response hashes, duplicate IDs, holdout selection, failed judge calls,
and old-run immutability. Run app/homework and isolated judges checks separately.
No live calibration claims arise from format reuse. Estimate: 2–4 days; medium risk;
coursework/canonical-runner decision required.

## Priority, dependencies, and completion criteria

Implement namespace flattening first if a quick navigation win is wanted; it is largely
independent. Next narrow prediction contracts after the data-compatibility decision,
then simplify common cost-query mechanics without changing UI behavior. Review-role
and evaluation changes can proceed independently after their requirements are fixed.
Streaming consolidation follows agreed event contracts. Mock presentation and polling
behavior wait for UI stabilization and an explicit product decision.

For each change, record before/after responsibilities, preserved behavior, API/data
impact, actual checks, and any deliberately retained complexity in the review. Complete
an app startup and deterministic assessment without keys/cache, preserve evidence hashes,
and run relevant existing checks before broader suites. Do not add a new abstraction
solely to reduce duplicated line count. A follow-up is complete only when navigation,
commands, capture/replay, and supported behavior remain understandable and reproducible.
