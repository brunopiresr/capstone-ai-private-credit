# Agent tools reference

Agents use application tools to retrieve evidence, read borrower financials, run
deterministic covenant calculations, and request forecasts or credit reviews. This
reference covers all eight tools exposed by `CreditAssessmentAgent` and the two
additional tools in the monitoring homework demo. It describes their arguments,
results, scope, and effects on saved data.

## Availability and scope

The [agent facade](../../src/credit_monitoring/agents/credit_assessment.py) registers
tools for each call or conversation according to application configuration:

| Configuration | Available tools |
| --- | --- |
| `service` (document service) | `list_documents`, `get_document_extraction`, `search_evidence`, `process_document` |
| `assessment_service` plus explicit `borrower_id` | `list_financial_periods`, `get_financials`, `assess_covenants`, `predict_risk` |
| Both services and borrower selection | All eight tools |
| `assessment_service` without borrower selection | No borrower tools; the assistant can explain or request selection |

Web V2 uses the saved-assessment adapter with borrower tools and recalculation
disabled. It does not configure document tools in its chats. The full tool set is
demonstrated in notebooks; **Documents & Data** uses document services directly.

`document_tool_names` can restrict the document tools to a subset. If `ticker` is
configured, document listing/search and reads/processing enforce that issuer scope.
Without configured ticker scope, listing/search may cover the catalog or accept a
ticker filter. Borrower selection is application-owned and is not a tool argument;
naming another borrower in chat does not change it. Conversations retain their
scope; start a new one to change borrower or issuer.

Document research needs no borrower or financial dates. A real SEC issuer and a
synthetic financial borrower are separate identities. Using extracted terms in a
borrower calculation requires explicit source bindings and supported calculation
rules; see [document-backed assessments](../guides/covenant-assessment.md#consume-stored-document-covenants).

## Document tools

Implemented by [DocumentTools](../../src/credit_monitoring/agents/tools/documents.py)
over [DocumentProcessingService](../../src/credit_monitoring/application/document_processing_service.py).
String arguments are strict strings; document IDs and search queries must be nonempty.

### `list_documents(ticker=None)`

- **Purpose:** discover catalog document IDs and processing states, including
  documents that have not been processed.
- **Arguments:** optional `ticker: str | None`; omitted/null uses configured issuer
  scope, or the whole catalog when no issuer scope exists.
- **Returns:** `list[DocumentSummary]` containing IDs, citations, ticker, status,
  cache metadata, section counts, and any processing error. Extraction facts are
  excluded. An empty list means no matching documents.
- **Effects:** reads catalog/stored state; no download or model request.

### `get_document_extraction(document_id)`

- **Purpose:** read complete stored covenant terms, threshold schedules, and
  reported values with their source references.
- **Arguments:** exact catalog `document_id: str`, within configured issuer scope.
- **Returns:** `DocumentExtraction`, including processing status and `result`.
  Status can be `missing`, `stale`, `processing`, `failed`, `complete`, or
  `unavailable`; only a complete current extraction exposes facts.
- **Effects:** reads stored state; no extraction model request or download. If
  needed facts lack a current extraction, use `process_document`.

For complete schedules, preserve every named quarter, range, and thereafter term.
Search excerpts alone do not establish that a schedule is complete.

### `search_evidence(query, ticker=None)`

- **Purpose:** retrieve filing passages supporting a question or supplementing
  structured extraction results.
- **Arguments:** nonempty `query: str` and optional `ticker: str | None`, with the
  same issuer-scope rules as `list_documents`.
- **Returns:** `list[RetrievedRecord]` with passage text, actual document IDs and
  citations, available source offsets, and catalog/retrieval metadata. MinSearch
  lexical retrieval returns up to ten passages, at most two per filing. No matches
  yields an empty list.
- **Effects:** searches existing local Markdown; no download or model request.
  Prepare documents separately if local text is unavailable.

### `process_document(document_id)`

- **Purpose:** obtain a current extraction when required facts are not yet stored.
- **Arguments:** exact catalog `document_id: str`, within configured issuer scope.
  There is no `force` argument on the agent tool.
- **Returns:** `DocumentExtraction` with status, extracted facts when complete,
  citations, section progress, errors, and `cache_hit` information.
- **Effects:** may download cataloged HTML, convert it to Markdown, invoke the
  extraction model for document sections, and persist progress/results in SQLite.
  Successful current extractions are reused. Requires `OPENAI_API_KEY` for model
  extraction and an identifying `SEC_USER_AGENT` for uncached SEC downloads.

Only cataloged HTML sources are supported. Incomplete or failed processing remains
explicit; automatic post-extraction verification is disabled. For cache identity,
section handling, and direct-service batch/force APIs, see
[processing and reuse](../guides/document-processing.md#processing-and-reuse).

## Financial, calculation, and prediction tools

Implemented by [AssessmentTools](../../src/credit_monitoring/agents/tools/assessment.py)
over [AssessmentService](../../src/credit_monitoring/application/assessment_service.py).
All four operate on the application-selected borrower and active financial source.

### `list_financial_periods()`

- **Purpose:** discover available reporting periods before reading or calculating.
- **Arguments:** none.
- **Returns:** `FinancialPeriodCatalog` with `borrower_id`, periods in ascending
  order, known `available_at` dates, `source` (`financial_repository` or
  `saved_assessment`), and `source_assessment_run_id` when applicable. No financial
  metrics or calculations are included. An empty `periods` list means none are
  stored in that source.
- **Effects:** reads the active financial source; no calculation or forecast.

### Shared date arguments

The following three tools require `period_end` and `information_cutoff` as strict
ISO date strings (`YYYY-MM-DD`). The cutoff must be on or after the reporting
period. When `selected_dates` is configured, both arguments must exactly match it.

Preserve dates supplied by the user or selected/saved context. For a latest/current
request only, a missing cutoff may default to the supplied current date in
Europe/Lisbon, with the actual default disclosed in the answer. Historical requests
without a contextual cutoff and ambiguous dates require clarification. Unknown
availability dates remain unknown; storage/load times are not publication dates.

### `get_financials(period_end, information_cutoff)`

- **Purpose:** inspect raw financial inputs without calculating an assessment.
- **Returns:** `FinancialReview` containing borrower/dates, `current` financials
  for the exact requested period (or null), earlier `history`, provenance, and
  `issues`. Records known to be unavailable by the cutoff are excluded and
  reported; unknown availability is disclosed. Another period is not substituted.
- **Effects:** reads financial data; no calculation, forecast, or new assessment.

### `assess_covenants(period_end, information_cutoff)`

- **Purpose:** calculate current covenant compliance, headroom, and historical
  results using the service's supported rules.
- **Returns:** `RiskAssessment` with current/history calculations, applicable
  terms, provenance, verification, run identity, and gaps. ML is disabled.
- **Effects:** loads its own financial inputs and runs deterministic assessment.
  With the live assessment service, each call creates a new run and persists
  eligible results; a preceding `get_financials` call is optional.

### `predict_risk(period_end, information_cutoff)`

- **Purpose:** assess current covenants and request the configured forecast model.
  Pass the base reporting period, rather than the future target quarter; the
  service determines the forecast horizon.
- **Returns:** `RiskAssessment` including current compliance/history, model
  metadata and prediction when available, or explicit ML unavailability and
  limitations. A stub supplies no probability. The Logistic Regression baseline
  was trained on synthetic histories; unknown source availability limits
  point-in-time reliability.
- **Effects:** loads its own inputs and enables ML on the assessment service.
  A separate financial read or covenant assessment is optional. Live execution
  can persist calculation results, feature snapshots, and predictions. Model
  selection belongs to the application, not the tool arguments.

Missing inputs, conflicting terms, waivers, inactive tests, and unavailable models
retain their service statuses. Structured verification covers calculations and
service results, not the truth of generated prose. See
[quarterly assessment and ML](../guides/covenant-assessment.md).

### Saved-assessment chat behavior

In workspace chats, [SavedAssessmentChat](../../src/credit_monitoring/application/borrower_workflow.py)
adapts these same tools to the selected saved assessment. Discovery and financial
reads cover only that snapshot and its history. By default, assessment calls return
a copy of the saved result instead of creating a new run. A forecast request on a
snapshot with ML disabled requires enabling recalculation and choosing a prediction
mode. With recalculation enabled, the adapter creates and reuses a new assessment
for that adapter instance. Changing borrower or dates requires changing the
application selection. V2 does not expose a recalculation toggle; the enabled
behavior described here is an adapter capability for Python callers.

## Monitoring homework tools

The [monitoring demo](../../homework/monitoring/README.md) exposes two additional
tools in **Credit Analysis** mode, implemented by
[ChatBackend](../../homework/monitoring/monitoring_backend.py). These are separate
from the eight application tools above.

| Tool and arguments | Result and effects |
| --- | --- |
| `list_borrowers()` | Returns a dictionary with synthetic borrower records and their available `reporting_periods`. Reads workspace data; discovered dates do not authorize an analysis. |
| `run_credit_review(borrower_id, period_end, information_cutoff, credit_criteria, ml_mode="Logistic Regression", constraints=None, refresh=False)` | Returns `CreditReviewResult`: deterministic assessment, optional ML, bullish/bearish analyses, and synthesized recommendation. May persist assessment outputs and makes review model requests. Identical requests reuse the session's cached review unless explicitly refreshed. |

`run_credit_review` accepts a borrower ID string, date arguments, a nonempty list of
credit criteria, optional string-list constraints, and ML mode `Logistic Regression`,
`Stub`, or `Off`. Borrower, reporting period, cutoff, and criteria must come from
user messages; the coordinator asks for missing details. The borrower and period
must exist, and cutoff must be on or after the reporting date. An unspecified ML
preference defaults to Logistic Regression and is disclosed. `refresh=True` is for
an explicit request to rerun. Invalid inputs use `ModelRetry`; failures are surfaced
in the demo's activity and answer state. The coordinator limits each turn to eight
model requests and six tool calls; nested review agents have their own limits.

**Evidence Search** mode reuses only `list_documents` and `search_evidence` from
the application tools. It cannot process documents or download sources.

## Output tools, execution, and inspection

The assistant's `final_result` is a structured output tool for returning its answer.
It does not retrieve evidence or execute a business operation. Its source-table
selections can copy complete schedules or reported values from loaded extractions.
Bullish, bearish, recommendation, and follow-up-question agents also use
`final_result` for typed output; the extraction agent uses schema-based `ToolOutput`.
These agents have no additional business function tools. The review workflow supplies
their evidence; they do not independently calculate compliance or search the web.

The eight application tools use strict schemas and sequential execution through
[common wrappers](../../src/credit_monitoring/agents/tools/common.py). Expected
service exceptions become `ToolFailure(code="service_error", message=...)`;
scope/date rejections use `invalid_arguments`. Rejected schemas and unknown tool
calls are recorded as `invalid_arguments` or `unknown_tool`. Unexpected exceptions
are not converted by the service wrapper. Document processing can also return a
failed `DocumentExtraction` rather than a `ToolFailure`.

The assessment assistant defaults to six tool rounds, with a model-request cap of
eight to allow final output and validation retry. Budgets reset each conversation
turn. Limit or model failures return an incomplete answer; service actions already
completed remain saved.

Inspect `AgentAnswer.tool_trace` for executed tool names, arguments, typed outcomes,
and sources. `AgentAnswer.evidence` retains evidence entries; `sources` comes from
actual results rather than model-authored citations. Streaming exposes `tool_call`
and `tool_result` events. See [assistant APIs and examples](../guides/agents.md#assessment-assistant),
the [agents notebook](../../notebooks/03-agents.ipynb), and
[Logfire setup](../guides/monitoring.md) for usage and optional telemetry.
