# SEC covenant extraction V2

The notebook now uses importable evidence extraction models and pipeline helpers.
The web app, its demo service, and unrelated evidence caches are unchanged.
No governing-amendment selection, covenant calculations, inferred compliance,
agents, vector database, or orchestration framework were added.

## Interfaces and migration

`credit_monitoring.domain` exports all V2 contracts. Every Pydantic field has a
description. Numerical values remain strings; explicitly supported dates serialize
as ISO 8601. Missing optional fields are null and collections are independent empty
lists. Unknown/old fields are rejected instead of silently discarded.

Single-company extraction returns `ExtractionResult` with `schema_version`,
`prompt_version`, `extraction: CovenantExtraction`, and `validation`. Callers should
inspect `validation.is_valid` and its `issues` before using extracted data. Issues
have `severity`, `code`, `path`, and `message`. Unverified facts remain unchanged;
errors do not cause a synthetic correction or an automatic retry.

```python
from credit_monitoring.covenants.extraction import extract_covenants

# Supply an existing OpenAI client and already-retrieved record dictionaries.
result = extract_covenants(query, search_results, client=client)
print(result.extraction.model_dump_json(indent=2))
print(result.validation.model_dump_json(indent=2))
# Persist the full wrapper if validation/version information must travel with facts.
serialized = result.model_dump_json(indent=2)
```

Changes from V1:

| Before | V2 |
| --- | --- |
| Flat evidence fields on each object | Nested `evidence: SourceEvidence`, including supplied `source_end` |
| `EBITDABasis` / `ebitda_bases` | `FinancialMetricDefinition` / `financial_metric_definitions` |
| Disclosed amount inside an EBITDA definition | Separate `ReportedFinancialValue` when actually reported |
| `ebitda_basis_name` | `metric_definition_name`, with an explicit source link only |
| Result/status inside a covenant | Separate `ComplianceDisclosure` |
| Combined amendment/waiver text | `AgreementAmendment` and/or `CovenantTestingEvent` |
| Unbounded schedule entries | Named dates, bounded ranges, open-ended starts, measurement basis |
| Direct `CovenantExtraction` return | Versioned result containing extraction and validation report |
| Batch company fields duplicated V1 | `company`, `ticker`, and complete V2 `extraction` per company |

The batch extractor still makes one request using
`AllCompanyCovenantExtraction` as the outer schema. It checks ticker coverage,
duplicate entries, catalog names, nested tickers, and each company's evidence
against that company's supplied records. Sparse companies remain entries with
gaps. No model request occurs when evidence or the catalog is empty.

```python
from credit_monitoring.covenants.extraction import extract_all_companies
from credit_monitoring.ingestion.loaders.sec import build_company_catalog

result = extract_all_companies(
    query, documents,
    company_by_ticker=build_company_catalog(filing_documents),
    client=client,
)
for company in result.extraction.companies:
    print(company.ticker, company.extraction.model_dump())
```

No stored V1 extraction output or application extraction consumer was discovered.
The notebook is migrated directly; no historical adapter was added. External V1
JSON must be migrated deliberately rather than manufacturing missing quotations,
dates, IDs, or provenance. The existing JSON evidence caches are a separate
format and were not converted.

## Reusable modules and changed files

All module paths below are relative to `src/credit_monitoring`.

| Layer | Files and responsibilities |
| --- | --- |
| Domain | `domain/{base,evidence,documents,covenant,financials,validation}.py`, `domain/__init__.py`: V2 models, retrieved inputs, reports, exports |
| Prompts | `agents/prompts/{extraction,batch,narrative,assembly}.py`: exact authoritative prompt, grouping, evidence-only narrative, JSON envelopes |
| Loaders | `ingestion/loaders/sec.py`: download, CSV catalog, company catalog, filing document preparation |
| Cleaning | `ingestion/cleaners/sec_html.py`: extracted Beautiful Soup cleanup |
| Conversion | `ingestion/converters/sec_markdown.py`: existing cache/versioned HTML-to-Markdown conversion |
| Chunking | `ingestion/chunking/evidence.py`: keyword neighbors, truncation, existing gitsource chunking, record preparation |
| Retrieval | `retrieval/lexical/sec.py`: MinSearch index, ticker filter, two ranked records per filing |
| Extraction | `covenants/extraction.py`: existing Responses parse API, single/batch flows, typed failures |
| Verification | `verification/extraction.py`: exact provenance and structural checks |
| Narrative | `application/rag_service.py`: reusable model invocation and RAG orchestration |

Other changes: `notebooks/02-rag.ipynb`, `pyproject.toml`, `uv.lock`,
`agents/prompts/README.md`, this document, and the new test files listed below.
Existing changes in the setup notebook, financial loader/repositories, persistence,
README, and gitignore were left intact.

Configure paths and dependencies at the call site. For example:

```python
from credit_monitoring.ingestion.loaders.sec import create_documents
from credit_monitoring.ingestion.chunking.evidence import chunk_evidence_documents
from credit_monitoring.retrieval.lexical.sec import build_index, search

filing_documents = create_documents(
    source_file, html_dir=html_dir, markdown_dir=markdown_dir,
    user_agent=sec_user_agent,
)
documents = chunk_evidence_documents(filing_documents)
index = build_index(documents)
search_results = search(query, index=index, document_count=len(documents), ticker=ticker)
```

Imports do not construct clients, download documents, create data directories,
convert files, or build indexes. Downloads need a caller-supplied SEC User-Agent;
cached files can be reused without it. The notebook reads `SEC_USER_AGENT` from
the environment rather than impersonating the former hard-coded contact.

The conversion marker remains `beautifulsoup-clean-v1`. Evidence selection uses
the original keyword regex, neighboring lines, deduplication, and 3500-character
limit. Chunk defaults remain size 3500 and step 500. Truncation is now tracked.

## Prompts, provenance, and known limitations

`EXTRACTION_INSTRUCTIONS` is copied verbatim from the agreed guide, including its
newlines, and versioned as `sec-covenant-extraction-v2.0`. Changing it requires a
separately reviewed prompt-version update. Batch grouping is a separate directive
that changes the outer return shape while reusing the full extraction rules.
Narrative RAG also reports only source-stated facts, without calculation.

Input assembly is JSON: original `text`, exact `document_id` and `citation`, and
optional path/start/end values only when supplied. Catalog notes are separated in
`catalog_context`; truncation and coordinates are in `retrieval_metadata`.

`gitsource.start` is copied into `source_start`. Its coordinate system is the
keyword-selected excerpt, which joins stripped/deduplicated lines; it is not an
offset into the Markdown file. Missing starts remain null. No absent `source_end`
is derived. Known length checks use the same coordinate system, and unspecified
coordinates are flagged for review.

Evidence must match document/citation together, contain an exact quote, and copy
metadata from the same quote-supporting record. Distinct unresolved overlapping
records generate a warning; identical duplicates do not. Punctuation or Markdown
differences fail exact verification instead of being fuzzy-matched.

Validation checks explicit literal values, recognized operator wording, direction,
date order, and definition targets. Dates not recognizable as ISO or English dates
in their supporting quotes are flagged for review. Missing thresholds/definitions
and missing or ambiguous links are warnings; no links or gaps are auto-filled.
Truncation and source warnings are surfaced separately from unchanged facts.

These checks cannot prove semantic entailment, detect every source typo, establish
legal applicability, or guarantee model resistance to injected instructions.
Name inclusion alone does not prove an explicit contractual definition link.
Keep facts from different excerpts separate or flag unresolved support.

Typed generation failures are `ExtractionInputError`, `ExtractionRefusalError`,
`ExtractionIncompleteError`, `ExtractionParseError`, and `ExtractionResponseError`.
Response-level errors retain the SDK response ID when available; SDK exceptions
are chained. The SDK can raise a parsing exception before returning a response
for malformed partial JSON; that case surfaces as `ExtractionParseError` rather
than inventing an unavailable incomplete-response status or ID.

One-call batch extraction can exceed a model's context/output limits on larger
corpora. Such failures are surfaced; no silent evidence truncation, per-company
fallback, amendment reconciliation, or model-driven retry was introduced.

## Tests and verification status

**Tests were created but not run, and no live model evaluations were performed.**
Acceptance criteria therefore remain unverified. Static lint, Python/notebook
syntax inspection, and the offline lockfile consistency check are separate from
test execution.

New tests live in:

- `tests/unit/covenants/{test_v2_schema,test_v2_facts,test_prompts,test_narrative_rag}.py`
- `tests/unit/verification/test_extraction.py`
- `tests/unit/ingestion/test_sec_pipeline.py`
- `tests/unit/retrieval/test_sec_search.py`
- `tests/integration/workflows/test_sec_extraction.py`
- `tests/evaluation/extraction/test_local_sec_regression.py` (optional existing local source)
- `tests/fixtures/sec_covenant_v2/` and shared fixtures in `tests/conftest.py`

The controlled snippets cover all ten guide acceptance categories. Unit tests
check expected-output preservation and deterministic validation. Integration
tests use actual SDK response types and a mocked HTTP transport through the
installed SDK. Injection tests establish instruction/data isolation, not live
model compliance. None downloads SEC documents or needs API credentials; the
optional local-source regression skips when the ignored file is absent.

When test execution is requested, run from the repository root:

```bash
uv run pytest tests/unit/covenants tests/unit/verification/test_extraction.py \
  tests/unit/ingestion/test_sec_pipeline.py tests/unit/retrieval/test_sec_search.py \
  tests/integration/workflows/test_sec_extraction.py
uv run pytest tests/evaluation/extraction/test_local_sec_regression.py
```

Pydantic V2 is now explicit (`>=2.12.5,<3`), and the OpenAI minimum is the already
locked `2.30.0`, whose `responses.parse(..., text_format=...)` interface is used.
The lockfile keeps existing resolved versions and reflects these direct requirements.
