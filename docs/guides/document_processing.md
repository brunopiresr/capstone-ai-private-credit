# Document processing and assistant APIs

The document service downloads cataloged HTML, converts it to Markdown, extracts
supported facts from every section, and stores results in SQLite. Search retrieves
local passages; the assistant uses scoped tools to answer questions with evidence.
For app controls, see [Documents & data](ui_preview.md#manage-documents-and-data).

## Process and search documents

Configure `OPENAI_API_KEY` for extraction and an identifying `SEC_USER_AGENT` for
uncached downloads. Call from synchronous application code:

```python
import os
from pathlib import Path
from credit_monitoring.application.bootstrap import create_document_service

service = create_document_service(
    source_file=Path("data/app/sec/public_sec_documents.csv"),
    html_dir=Path("data/cache/sec/html"),
    markdown_dir=Path("data/cache/sec/markdown"),
    database_path=Path("data/runtime/covenants.sqlite3"),
    user_agent=os.environ.get("SEC_USER_AGENT", ""),
)
document = service.process_document("DOC_FMC_AMD3_2025")
print(document.cache_hit, document.result.extraction.model_dump())

outcomes = service.process_documents(
    ["DOC_FMC_AMD3_2025", "DOC_FMC_Q1_2025"], max_workers=4,
)
failures = [item for item in outcomes if item.status == "failed"]
passages = service.search_evidence("interest coverage", ticker="FMC")
```

The factory accepts `model`, `source_file`, `html_dir`, `markdown_dir`, `database_path`,
and `user_agent` overrides. See [cache locations and downloads](../../data/README.md#sec-source-download).
In notebooks, run synchronous processing with `await asyncio.to_thread(...)`.

`process_all_documents(ticker=None, force=False, max_workers=4)` handles the catalog.
Batches default to four document workers, preserve input order, and retain individual
failures. Sections within each document run sequentially. Select one worker for
sequential processing. Injected model/converter instances need resource factories for
parallel use. SEC downloads retain shared pacing.

Listing stored state and searching local evidence make no model requests or downloads.
Search returns up to ten passages, at most two per filing. Read stored extractions for
complete schedules; a few retrieved passages cannot establish completeness.

## Processing and reuse

- Only registered document IDs can be processed; HTML is supported, PDF is not.
- Full Markdown is split at structural boundaries with a default 60,000-character
  request budget. Oversized indivisible blocks fail explicitly; text is not truncated.
- Cache identity includes source/metadata hashes, model, prompt, schema, conversion,
  segmentation, and text budget. Changed inputs make earlier results stale.
- Successful sections survive failure. A complete document publishes only after all
  sections succeed. Distinct historical facts remain separate; legal precedence is unresolved.
- `force=True` reruns every section. A failed forced run does not expose its old result
  as current. Historical versions remain stored.
- Reads distinguish missing, stale, unavailable, processing, failed, and complete states.
  Only complete/current results contain facts.

Automatic post-extraction verification is disabled: wrapper schema `2.1` uses
`validation: null`. Parsing and evidence requirements remain active. Extraction prompt
`v2.3` separates reported actuals from limits, preserves source names, and records
contradictory headings. Batch instructions remain `v2.1`.

## Ask questions

```python
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent

agent = CreditAssessmentAgent(model=service.model, service=service)
answer = await agent.ask_async("Show FMC's covenant schedule with citations.", ticker="FMC")
print(answer.answer, answer.sources, answer.tool_trace)
```

Use `ask(...)` in synchronous code. Each independent call starts fresh. The default
allows six tool rounds and seven model requests, including output-validation retries.
Limit, refusal, or output failures return explicit incomplete results.

Document tools list sources, read extractions, search evidence, and process a document.
Ticker scope is enforced by adapters; the agent cannot force reprocessing. Public answers
retain actual tool outcomes and sources. Confidence describes evidence support;
it is not a calibrated probability or verification result.

### Conversations and follow-up questions

```python
conversation = agent.start_conversation(ticker="FMC")
first = await conversation.ask_async("Find the leverage schedule.")
follow_up = await conversation.ask_async("Which filing supports that threshold?")
conversation.close()
```

Conversations retain questions, tool results, and citations in memory. Scope stays fixed;
start a new conversation to change it. Tool budgets reset each turn. Exact `close`,
`done`, or `quit` messages also close locally. Failed turns preserve earlier successful
history; already completed service actions remain saved.

### Streaming and diagnostics

`stream_async()` emits `model_start`, `tool_call`, `tool_result`, `answer_update`, and
`run_end`. Replace the displayed provisional answer on each update; only
`run_end.answer` is final. Use `contextlib.aclosing` when consuming a stream that may
end early. An async `event_stream_handler` receives progress; callback failures propagate.

`configure_logging()` from `credit_monitoring.observability.logging` enables console
progress. See [Logfire setup](logfire_setup.md) for optional traces. Public events
exclude private model reasoning. Source lists record available evidence, not semantic
verification of every generated claim.

## Calculation and prediction tools

Inject an `assessment_service` and pass explicit `borrower_id` scope to enable:

| Tool | Result |
| --- | --- |
| `get_financials` | Sanitized current metrics and bounded history |
| `assess_covenants` | Verified calculations with ML disabled |
| `predict_risk` | Assessment plus the configured model's output or explicit unavailability |

Tools accept ISO reporting and information-cutoff dates. Each assessment call creates
a new run. Missing terms, inputs, conflicts, waivers, and inactive tests retain their
service outcomes. The default stub supplies no probability.

An assessment-only agent can omit the document service. Financial borrowers and SEC
issuers are never matched automatically. Document-backed calculations need explicit
`ExtractionBinding` and established calculation rules; see the
[assessment guide](ml_early_warning.md#consume-stored-document-covenants).

Tool outcomes are typed domain objects, with recoverable errors represented by
`ToolFailure`. Serialize with `model_dump(mode="json")` only when exporting. Notes and
gold labels are excluded from inputs; scope and date checks remain application-owned.

## Examples and checks

The [RAG notebook](../../homework/notebooks/02-rag.ipynb) demonstrates retrieval;
the [agents notebook](../../homework/notebooks/03-agents.ipynb) adds scoped tools,
conversations, and assessments. For an offline throughput measurement:

```bash
uv run --locked python scripts/benchmark_document_processing.py \
  --output data/runtime/document-processing-benchmark.json
```

This simulates model I/O. It does not measure live provider speed or extraction quality.
See [evaluation](../homework/evaluation.md) and [public SEC findings](../reviews/public_sec_benchmark_triage.md).
