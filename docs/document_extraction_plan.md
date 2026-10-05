# Complete document extraction and a RAG agent loop

Agreed on October 4, 2026. Saved for implementation on October 5, 2026.
Status: implemented on October 5, 2026; changes are uncommitted. See
[usage and implementation notes](document_processing.md).

## Summary

Build a synchronous document-processing service that extracts and stores all relevant
facts. The application waits for its result. Unchanged documents reuse stored
extractions.

Add a RAG agent loop in the same implementation. The agent uses tools to discover
documents, read stored facts, search source passages, and process documents when
needed. Document ingestion remains a complete, systematic service operation.

The missing fiscal quarters originate upstream: keyword selection retains a table
heading and its first neighboring row while dropping subsequent rows. It also caps
selected evidence at 3,500 characters. The current prompt already requests every
schedule entry, but the model does not receive complete tables.

## Processing and tool interfaces

- Add an application service configured with the client, model, catalog, source
  directories, and SQLite path.
- Expose `process_document(document_id, force=False)`,
  `get_document_extraction(document_id)`, and
  `list_document_extractions(ticker=None)`. Resolve document IDs through the catalog.
- Expose `search_evidence(query, ticker=None)` around existing retrieval, returning
  source records and citations without generating an answer.
- Keep these methods independent of notebooks and UI. The agent calls them through
  thin tool adapters with simple, serializable arguments and injected service
  configuration.
- Processing always traverses the complete document. Its extraction scope does not
  depend on an analyst question or an agent's retrieval choices.

## Complete extraction and storage

- Load full Markdown through existing conversion helpers. Bypass keyword selection,
  its 3,500-character truncation, and ranked retrieval for structured extraction.
- Extract every supported covenant version, fiscal-quarter schedule, definition,
  amendment, testing event, reported value, compliance disclosure, and facility term.
- Version the prompt and explicitly require complete tables, continuation rows, and
  exact threshold wording such as `"4.00 to 1.00"`.
- Use one model call up to a configurable default of 60,000 characters. Split larger
  documents at structural boundaries while preserving complete tables, introducing
  clauses, and continuation rows. Supply necessary heading context separately with
  accurate source offsets.
- Report an error for an indivisible block exceeding the configured budget; never
  silently truncate it.
- Combine section results deterministically, removing exact duplicates while
  preserving distinct versions and unresolved conflicts. Do not infer governing
  terms.
- Store metadata, complete extraction JSON, and successful section results in
  SQLite, separately from quarterly financial snapshots.
- Identify reusable results by document ID, source text and metadata hash, model,
  schema, prompt, and segmentation versions. Changes or `force=True` trigger
  reprocessing.
- Reuse successful sections after failure. Publish a complete document result only
  after every section succeeds.
- Update notebook structured-extraction examples to invoke the service. Keep
  query → index → answer available independently.

## RAG agent loop

- Implement the orchestrator in the existing `agents/monitoring.py` boundary and
  adapters in `agents/tools/`. Use the existing model client; add no agent framework.
- Expose `ask(question, ticker=None)`, returning an answer, source references, and
  a tool execution trace containing tool names, arguments, and outcomes. Do not
  include private model reasoning in the trace.
- Make four tools available: list catalog documents and their processing state,
  read a stored document extraction, search evidence, and process a document. The
  catalog listing must include unprocessed documents so the agent can discover
  them. Reading missing or stale facts returns that state rather than pretending
  facts are absent from the source.
- Flow: analyst question → model chooses tools → Python executes tools → results
  return to the model → another tool call or a final cited answer. RAG occurs when
  retrieved passages are supplied to the model as tool results.
- Reuse stored facts first for complete covenant schedules; use evidence search
  for supporting passages and questions beyond those facts. Processing calls use
  normal cache behavior; forced reprocessing is an application action, not an
  agent tool argument.
- Validate tool names and argument shapes before dispatch. Return expected service
  failures as explicit tool results so the agent can explain missing information.
  Keep model refusal, incomplete-response, and API-error handling explicit.
- Default to at most six tool rounds, executing calls sequentially within a round.
  If the limit is reached, return an explicit incomplete result with the available
  sources and trace rather than claiming the question was fully answered.
- Treat retrieved passages and stored facts as evidence, never instructions. Cite
  source document IDs and supplied citations; disclose relevant gaps and conflicts.
  Do not infer governing terms, compliance, or calculated values.
- Demonstrate the loop in the notebook with a question requiring both stored
  covenant schedules and retrieved filing passages. Keep the existing direct RAG
  function available. Financial calculation tools and Streamlit integration remain
  outside this implementation.

## Temporarily disable validation

- Comment out automatic validator imports, calls, and report-building blocks in
  both existing extraction flows. Add a note explaining the temporary POC decision
  and restoration steps.
- Preserve the validator implementation and standalone tests.
- Make result-wrapper `validation` nullable; return `null` when verification has
  not run. Version the wrapper contract as `2.1`, keeping the LLM's fact schema
  unchanged.
- Update documentation and notebook output so skipped verification is not reported
  as passed. Retain Pydantic parsing and existing model-error handling.

## Tests and acceptance

- Add a tracked FMC fixture covering all **19 leverage quarters** and **17
  interest-coverage quarters**. Verify complete input delivery, schedule
  serialization, and exact threshold wording.
- Test section boundaries, continuation tables, source offsets, exact
  deduplication, and preservation of distinct versions.
- Verify cache hits make zero model calls; content/configuration changes and forced
  processing invalidate cached results.
- Verify failures do not publish complete results and successful sections are
  reused on retry.
- Test service lookup by document ID, retrieval by ticker, and evidence search
  without answer generation.
- Test the agent loop with mocked model responses that choose multiple tools, read
  their results on subsequent rounds, and return a cited answer. Check catalog
  discovery of unprocessed documents, missing/stale extraction handling, and
  processing-tool cache reuse.
- Test unknown tools, malformed arguments, tool failures, model failures, and the
  six-round limit. Verify the returned trace demonstrates actual tool execution
  and does not expose private model reasoning.
- Assert automatic verification is not invoked and `validation` is `null`;
  preserve independent validator coverage.
- Run the full test suite, lint, and notebook syntax checks. Mocked tests verify
  pipeline behavior; actual LLM completeness requires a separately invoked live
  extraction.

## Assumptions and defaults

- No queue, background worker, new Streamlit controls, or agent framework.
- The application invokes the processing service directly and waits for its result.
- LLM extraction remains in use; Python loads, segments, combines, and stores the
  results.
- "Parse once" means reuse a successful extraction for each document version;
  large documents may require multiple section calls.
- The RAG agent loop is included. It orchestrates tool use for analyst questions;
  it does not decide which parts of a document the extraction service processes.
- Financial calculation tools and analyst UI integration are deferred.

## Repository handoff

Relevant existing boundaries:

- `src/credit_monitoring/application/`: application services and existing narrative
  RAG orchestration.
- `src/credit_monitoring/covenants/extraction.py`: structured single-company and
  batch extraction; automatic validation call sites.
- `src/credit_monitoring/ingestion/loaders/sec.py`: catalog and converted filing
  loading; currently selects and truncates evidence.
- `src/credit_monitoring/ingestion/chunking/evidence.py`: keyword selection and
  existing retrieval chunk preparation.
- `src/credit_monitoring/persistence/`: existing SQLite connection and schema
  helpers.
- `src/credit_monitoring/domain/validation.py`: result wrappers and validation
  report types.
- `src/credit_monitoring/verification/extraction.py`: retain deterministic
  verification implementation.
- `src/credit_monitoring/agents/`: existing placeholders to implement the monitoring
  agent loop and tool adapters.
- `notebooks/02-rag.ipynb`: current query-based structured extraction examples.

The local FMC source is
`data/sec_documents/markdown/DOC_FMC_AMD3_2025.md`. Its leverage schedule spans
June 30, 2023 through December 31, 2027; its interest-coverage schedule spans
December 31, 2023 through December 31, 2027. Both schedules include continuation
or surrounding clause context that must reach extraction. SEC source files are
ignored by Git, so regression tests need a tracked fixture.

Before implementing, inspect the current working tree and preserve existing edits.
This document preserves the agreed plan. The implementation is available through
the document-processing service, monitoring agent, and updated RAG notebook.
