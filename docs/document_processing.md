# Complete document processing and the credit assessment agent

The application invokes a synchronous service. It reads complete filing Markdown,
extracts supported facts with the existing LLM, stores them in SQLite, and returns
the result. No queue or worker is needed. Analyst questions can independently use
the RAG agent's tools to read facts and retrieve source passages.

```mermaid
flowchart LR
    D[Catalog document] --> P[Complete Markdown extraction]
    P --> DB[SQLite facts and section cache]
    D --> I[Local Markdown search index]
    Q[Analyst question] --> A[Credit assessment agent]
    A --> T[Read facts / search passages / process document]
    DB --> T
    I --> T
    T --> A
    A --> R[Cited answer and tool trace]
```

## Invoke from application code

```python
from pathlib import Path
from openai import OpenAI
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.observability.logging import configure_logging

# Show timestamped progress in the console or notebook cell output.
configure_logging()

service = DocumentProcessingService(
    client=OpenAI(),
    source_file=Path("data/public_sec_documents.csv"),
    html_dir=Path("data/sec_documents/html"),
    markdown_dir=Path("data/sec_documents/markdown"),
    database_path=Path("data/processed/covenants.sqlite3"),
    user_agent="Your organization contact@example.com",
)

document = service.process_document("DOC_FMC_AMD3_2025")
facts = document.result.extraction
print(document.cache_hit, facts.model_dump())

# Process every catalog document, reusing complete/current extractions.
outcomes = service.process_all_documents()
failures = [(item.document_id, item.error) for item in outcomes if item.status == "failed"]

# Optional issuer filter or explicit reprocessing.
# outcomes = service.process_all_documents(ticker="FMC")
# outcomes = service.process_all_documents(force=True)

# State inspection and evidence search do not invoke the model or download files.
documents = service.list_document_extractions(ticker="FMC")
passages = service.search_evidence("interest coverage", ticker="FMC")

agent = CreditAssessmentAgent(client=service.client, service=service)
answer = agent.ask("Show FMC's complete covenant schedules with filing evidence.", ticker="FMC")
print(answer.answer)
print(answer.sources)
print(answer.tool_trace)
```

Progress logs show the current document (`document=2/10`) and section
(`section=3/8`), source download/cleanup/conversion, cache reuse, model and input
size, SQLite saves, and a final batch count of completed/failed/cached documents.
Each critical step logs before it starts and reports `elapsed_s` when it completes
or fails. During a model request, the latest `Extract section started` entry
identifies the active request; its duration appears when that request returns.
Failed steps log the exception type; detailed errors remain in returned outcomes.
Document text, prompts, model outputs, and credentials are not included in progress logs.

`configure_logging()` enables INFO console output for `credit_monitoring` only
and can be called repeatedly without duplicate handlers. Applications with existing
logging configuration can instead enable the `credit_monitoring` logger at INFO.
Call `configure_logging("WARNING")` to hide routine progress.

In notebooks or asynchronous application code, use the asynchronous entry point:

```python
answer = await agent.ask_async("Show FMC's covenant schedules with filing evidence.", ticker="FMC")
```

`ask()` uses a synchronous entry point and raises a usage error when an event loop
is already running. The agent accepts the existing synchronous `OpenAI` client;
model requests and tools run in worker threads as needed. For asynchronous
applications, an `AsyncOpenAI` client can instead be supplied to the agent and reused
within the application's event loop. The extraction service still uses its own
synchronous client.

`notebooks/02-rag.ipynb` demonstrates narrative RAG and direct document processing.
`notebooks/03-agents.ipynb` is the independent SDK agent walkthrough: client and service
setup, tool inspection, document questions, synthetic financial loading, and borrower
calculations/predictions with answer and trace inspection. Run its cells in order;
it does not depend on state from the RAG notebook. Notebook model cells require API
credentials. Existing direct narrative RAG remains available;
the service's evidence search indexes full local Markdown rather than keyword-selected
excerpts. Search returns up to ten ranked passages, at most two per filing. Complete
schedules should be read from stored extraction results rather than inferred from
those few passages.

## Processing and reuse

- Document IDs resolve through the CSV catalog. New catalog entries appear on the
  next service invocation. Only registered documents can be processed.
- Full Markdown is loaded through the existing download/conversion cache. Downloads
  require an identifying SEC User-Agent; source text is never silently truncated.
- The default extraction text budget is 60,000 characters per request, including
  separate heading context. This is a conservative operational setting, not an exact
  model token limit. Set `max_chars` to change it; API context/output failures remain
  explicit and no partial model output is accepted.
- Larger sources split at paragraph boundaries. Tables retain introducing clauses
  and continuation rows separated by page numbers/rules. An indivisible block larger
  than the budget raises `SectionTooLargeError` before extraction begins.
- Section offsets are measured character offsets in the original Markdown. Heading
  context is supplied as a separate record with its own offsets.
- Complete results and successful sections persist in `document_extractions` and
  `document_extraction_sections`. Transactions finish before model calls begin.
- Cache identity includes source text and metadata, model, schema, prompt, conversion,
  segmentation versions, and text budget. Unchanged documents reuse their result;
  changed inputs are stale until processing succeeds again.
- `process_document(id, force=True)` explicitly discards the matching cached run and
  processes it again. A failed forced run does not expose its previous successful
  result as current. Other historical content/configuration versions remain stored.
- `process_all_documents(ticker=None, force=False)` processes the catalog sequentially
  in CSV order and returns one `DocumentExtraction` per selected document. Individual
  failures return `status="failed"` with an error and do not stop later documents.
  Invalid catalogs raise before any processing. Source-loading errors are reported
  in the returned batch outcomes; extraction failures also retain the existing
  SQLite failure and section-recovery behavior.
- Failed section runs retain successful sections for retry. A complete document is
  published only after all sections succeed. Exact duplicate facts are removed;
  distinct versions are retained without legal reconciliation.
- Read methods return `DocumentExtraction` with explicit missing, stale, unavailable,
  processing, failed, or complete state. Only complete/current results contain facts.

Concurrent processing of the same document is not coordinated in this local POC;
invoke the service serially. Ingestion is systematic and independent of an analyst's
question; the agent chooses tools, not which sections ingestion should read.

## Agent behavior

The loop uses the OpenAI Agents SDK (`openai-agents`, imported as `agents`).
`CreditAssessmentAgent` configures an SDK `Agent` and invokes `Runner.run()` using the
Responses model adapter and four document tools:
`list_documents`, `get_document_extraction`, `search_evidence`, and `process_document`.
With an injected `AssessmentService` and an explicit `borrower_id` on the question,
it also exposes `get_financials`, `assess_covenants`, and `predict_risk`.
The SDK manages conversation history and tool continuation. The application retains
argument validation, issuer/borrower scope, document processing, assessments, source collection, and the
public `AgentAnswer` contract. Tool execution is sequential even if a response
contains several calls. Each question has separate context, sources, and trace.
See the [official OpenAI Agents SDK quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart?lang=python).

### Reuse the tool classes

`DocumentTools` and `AssessmentTools` expose explicit methods and a `.tools` property.
The property wraps their bound methods with SDK `function_tool()`. Tool descriptions
and argument descriptions come from each method's docstring; type annotations supply
the schemas. There are no separate tool-definition dictionaries or service dispatchers.
`self` and `ToolContext` are excluded from model-visible arguments.

Each instance owns its service and issuer/borrower scope. Another agent can reuse the
classes with its own configured services:

```python
from agents import Agent, RunConfig, Runner, ToolExecutionConfig
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.agents.tools.assessment import AssessmentTools

documents = DocumentTools(service, ticker="FMC")
tools = documents.tools

# Optional: assessment_service must already be configured, and the application
# must explicitly establish this borrower's relationship to the issuer.
# assessments = AssessmentTools(assessment_service, borrower_id="BORROWER_ID")
# tools += assessments.tools

research_agent = Agent[AgentRunState](
    name="Filing research agent",
    model="gpt-4o-mini",
    instructions="Use filing tools to answer questions with exact source citations.",
    tools=tools,
)
result = await Runner.run(
    research_agent,
    "Find FMC's leverage covenant and supporting filing passages.",
    context=AgentRunState(max_tool_rounds=6),
    max_turns=7,
    run_config=RunConfig(
        tracing_disabled=True,
        tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1),
    ),
)
print(result.final_output)
```

This direct SDK example returns SDK results. Use `CreditAssessmentAgent` for the
public `AgentAnswer`, collected citations and trace, custom round budget, and raw
response validation described below. Its SDK hooks collect successful and failed
tool outcomes. `AgentRunState` holds only execution counters, pending arguments,
sources and trace; it contains no services. Adding a service requires its tool
class and agent registration rather than a new context field. Create fresh tool
instances and state for each question to keep scope and execution state separate.

The shared validation helper rejects unexpected raw arguments before service
execution, including attempts to supply `force`, borrower overrides, or model
configuration. Expected argument and service failures remain JSON error results
the model can use on its next turn.

The default permits six tool rounds plus one model response to finish. A further
tool request returns `complete=False`, `error="tool_round_limit"`, and the existing
sources and trace. Model refusals, incomplete responses, empty responses and API
failures also return explicit incomplete outcomes. A client adapter rejects raw
non-completed Responses and refusals before tool dispatch. An SDK lifecycle hook
enforces the round budget before any calls in an excess round execute; the SDK's
maximum-turn setting also bounds the run. Multiple calls in one response count as
one tool round. Expected tool failures and unknown tools return error results the
agent can use to explain missing information.

Ticker scope is enforced by the tool adapters. The agent cannot force reprocessing;
that remains an explicit application action. The trace records requested arguments
and actual tool outcomes, including errors and cache hits. Private model reasoning
is retained only as needed for model continuation and is excluded from public outcomes.
`sources` lists evidence references actually returned by successful tools; it is not
a semantic verification of every claim in the generated answer.

SDK dashboard tracing is disabled by default. Set `tracing_enabled=True` on
`CreditAssessmentAgent` to enable tracing with sensitive input/output data excluded.
The application-owned `tool_trace` remains available with either setting. The
current agent starts a fresh conversation per question; persistent sessions,
streaming, and specialist handoffs are separate extensions.

## Verification and limitations

Automatic post-extraction verification is temporarily disabled for the POC. Imports,
calls, and report-building blocks are commented in `covenants/extraction.py`, with
restoration notes. The verifier implementation and standalone tests remain intact.
Restore those imports/calls and replace `validation=None` with the computed reports
to re-enable it; also update the service configuration version to invalidate cached
unverified results.

Result wrappers use schema version `2.1`; `validation: null` means verification did
not run. Callers must handle null rather than dereferencing `validation.is_valid`.
The LLM's V2 fact schema and required evidence are unchanged. Pydantic parsing and
SDK error handling remain active. Prompt versions are now extraction/batch `v2.1`;
the old `v2.0` prompt snapshot is retained alongside the new snapshot.

The agent reports source-supported facts and gaps. Calculations and configured-term
applicability are delegated to the assessment service; the agent never infers them
from filing prose. Automatic post-extraction verification and Streamlit integration
remain outside this implementation. Mocked tests establish
pipeline behavior, not live LLM completeness or resistance to injected instructions.

## Calculation and prediction tools

The renamed class lives in `credit_monitoring.agents.credit_assessment`; update
imports formerly using `credit_monitoring.agents.monitoring.MonitoringAgent`.
Document-only construction continues to work. To enable assessments, inject the
existing service; its repositories, covenant reader, calculation rules and model
configuration stay application-owned:

```python
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository

assessment_service = AssessmentService(
    financial_repository=FinancialRepository(Path("data/processed/financials.sqlite3")),
    covenant_reader=SyntheticCovenantReader(Path("data/synthetic_covenant_terms.csv")),
    settings=AssessmentSettings(
        analytics_database=Path("data/processed/agent_analytics.sqlite3"),
        risk_model=RiskModelConfig(type="stub"),
    ),
)
agent = CreditAssessmentAgent(
    client=service.client, service=service, assessment_service=assessment_service,
)
answer = agent.ask(
    "Assess covenant compliance and headroom for 2025-09-30, using an information "
    "cutoff of 2025-09-30. Also request a next-quarter breach prediction and explain "
    "whether the configured model supplies one.",
    borrower_id="SYN002",
)
```

Load the financial CSV first as described in the README. For a trained forecast,
replace the stub configuration with the explicitly selected Logistic Regression
artifact described in [ML usage](ml_early_warning.md#use-the-trained-model-in-assessments).
The default stub returns no probability. Trained baseline results describe a model
trained on simulated histories.

All three tools accept only ISO `period_end` and `information_cutoff` dates. Borrower
scope comes from `ask(..., borrower_id=...)`, not model arguments. If a question also
supplies `ticker`, the caller explicitly identifies its relationship to the borrower;
there is no automatic mapping between the synthetic borrowers and real SEC issuers.
For document-backed calculations, configure `ExtractionCovenantReader` with explicit
bindings and established `CalculationRules` as described in [assessment usage](ml_early_warning.md).
Without borrower scope only the document tools are registered. The agent requests
missing dates rather than choosing a reporting period or cutoff itself.

`get_financials` returns sanitized current metrics and bounded history with source
file/row provenance; notes and benchmark labels are excluded. `assess_covenants`
always disables ML. `predict_risk` runs the assessment service with ML enabled,
ensuring predictions refer to verified calculations and a persisted feature snapshot.
Each assessment call creates a new run, including when predictions follow a prior
calculation call. Model failures preserve the calculation results and appear as
explicit ML status and issues. Missing terms, unresolved formulas, waived tests and
missing inputs retain their existing abstention/status behavior.

The public `sources` collection retains filing citations, including those returned
by document-backed assessments. Financial CSV provenance, applied term evidence,
calculation IDs, feature snapshots and model metadata are available in `tool_trace`
outcomes and used in the final explanation. Structured assessment verification is
active; automatic document-extraction verification remains disabled. Neither proves
the semantic correctness of arbitrary generated prose. The UI remains a mock.

Before the SDK migration on October 5, 2026, all 29 existing local filings
partitioned losslessly into 107 sections with the default budget.

SDK migration verification on October 5, 2026: all 148 tests passed, Ruff,
formatting, whitespace, and offline lockfile checks passed, and both notebooks
passed JSON/Python syntax inspection. The agent tests use the real SDK runner with
mocked model responses, including synchronous and asynchronous HTTP clients,
tool ordering, round limits, failure handling, and concurrent read-only issuer scope.
No live model requests were made during implementation or verification.
