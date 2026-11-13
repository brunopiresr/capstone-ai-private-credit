# Document processing and evidence retrieval

An analyst needs the actual covenant clause and its dated schedule, not just a
plausible explanation. The document service downloads cataloged HTML, converts it
to Markdown, extracts supported facts from each section, and stores them in SQLite.
MinSearch retrieves local passages for inspection and RAG answers.

Use [Web V2 → Documents & Data](web-v2-workflow.md#documents--data) for the interface,
or [Notebook 02](../../notebooks/02-rag.ipynb) for the teaching sequence.

## Process and search documents

Extraction needs `OPENAI_API_KEY`; uncached SEC downloads also need an identifying
`SEC_USER_AGENT`. In synchronous code:

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
print(document.status, document.cache_hit)
if document.status == "complete":
    print(document.result.extraction.model_dump())
passages = service.search_evidence("interest coverage", ticker="FMC")
```

In notebooks, wrap synchronous processing with `await asyncio.to_thread(...)`.
The factory also accepts a `model` override. See [data downloads](../../data/README.md#sec-source-download).

`process_documents(document_ids, force=False, max_workers=4, progress=None)` handles
selected documents; `process_all_documents(ticker=None, force=False, max_workers=4)`
handles the matching catalog. Each worker owns its resources; injected clients or
converters need factories for parallel use. Sections inside each document remain
sequential. SEC downloads retain shared pacing. Results preserve input order and
individual failures. Choose one worker for sequential processing.

## Retrieval and RAG

Listing stored state and searching existing Markdown make no downloads or model
requests. Lexical search returns up to ten passages, at most two per filing.
`ticker` filters the Python search; the V2 evidence-index search covers all
cataloged local sources rather than the selected borrower.

RAG first retrieves passages, then asks the narrative model to answer from that
supplied evidence. The narrative model has no retrieval tools. Notebook 02 also
contains a keyword-selection teaching experiment; the application searches full
local Markdown through the retrieval-owned index.

Search excerpts can locate a relevant clause but cannot establish that a threshold
schedule is complete. Read the stored extraction and original source for every
named quarter, range, and thereafter term. No full-corpus quantitative retrieval
comparison has established the best configuration. Vector/hybrid search is deferred.

## Processing and reuse

- Only registered document IDs and HTML sources are supported; PDF is unsupported.
- Full Markdown is split at structural boundaries with a default 60,000-character
  request budget. Oversized indivisible blocks fail rather than being truncated.
- Cache identity includes source/metadata hashes, model, prompt, schema, conversion,
  segmentation, and budget. Changed inputs make old results stale.
- Successful sections survive failure. Current complete facts publish only when
  every section succeeds. Distinct historical facts remain separate.
- `force=True` reruns every section. If it fails, the old extraction is not exposed
  as current. Historical versions remain stored.
- Read statuses distinguish `missing`, `stale`, `unavailable`, `processing`,
  `failed`, and `complete`. Only complete current results expose facts.

Wrapper schema `2.1` has `validation: null`: automatic post-extraction verification
is disabled. Parsing and evidence requirements still apply. Prompt `v2.3` separates
reported actuals from limits, preserves source names, and records contradictory
headings; batch instructions remain `v2.1`. These instructions do not establish
extraction accuracy. [Public-source quality acceptance remains open](../evaluation/results.md#public-source-extraction).

## From a filing to an assessment

Synthetic borrowers and public issuers have different identities. Linking a source
does not resolve legal precedence, determine a formula, or replace financial inputs.
Document-backed calculations need explicit `ExtractionBinding` records and
established `CalculationRules`; otherwise, supported source-reported comparisons
can be labeled as reported. See [assessment methodology](covenant-assessment.md#consume-stored-document-covenants).

Agent conversations, streaming, and model limits belong in the [agents guide](agents.md).
For exact tool arguments, returned objects, and service effects, use the
[tool reference](../reference/agent-tools.md).

## Checks

Offline processing throughput can be inspected with:

```bash
uv run --locked python scripts/benchmark_document_processing.py \
  --output data/runtime/document-processing-benchmark.json
```

This uses simulated model I/O and real local storage. It measures orchestration,
not live-provider throughput or extraction accuracy. Behavioral checks are included
in `make test-all`; [evaluation](../evaluation/README.md) covers quality separately.
