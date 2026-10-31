# Streamlit POC: connected analyst and manager workflows

Run `make preview`, then open the Streamlit URL printed in the terminal. If another
app already uses the default port, run:

```bash
uv run --locked --extra ml streamlit run src/credit_monitoring/web/preview.py --server.port 8502
```

**Portfolio** and **Borrower analysis** share saved calculation and credit review
results. Analyst validation, flags, drafts and submitted reports persist locally.
**Risk review** records manager decisions and further-analysis requests against those
submissions. **Board report** saves draft/final snapshots of flagged cases and pending
items. **Documents & data** connects the working source catalog, extraction pipeline
and data maintenance. The original single-borrower app remains available through
`make run`. Reading pages never launches assessments or agents.

If a server was running during an update and reports an import error such as
`cannot import name 'AdditionalReviewContext'`, stop it with **Ctrl+C** and run
`make preview` again. Refreshing the browser does not clear Python's module cache.
Both app entry points now include shared `src/` modules in Streamlit's native watch
scope, so subsequent backend edits reload along with the pages. Restarting retains
the saved SQLite records.

## In-app guide and generated follow-up questions

Open **User guide** from any page's sidebar, or use Portfolio's dismissible
**New here?** invitation. The guide covers the assessment-to-submission path,
dates, evidence, agent reviews, forecasts, revisions, documents, manager decisions
and board reports. **Back to previous page** restores working selections and chat.
Use inline **How to…** sections without leaving an unfinished form. Save report
drafts before navigating; unsent forms are not automatically persisted.

After an explicit credit review, a separate read-only agent receives the exact saved
calculations and bullish, bearish and recommendation outputs. It writes up to three
specific follow-up questions, with reasons and references to those findings. The
questions are generated, not selected from a fixed question bank. This adds a model
request (with a bounded retry for invalid output) to each newly reviewed borrower,
including batch and manager context-only reviews. Failure preserves the saved review.

In **Borrower analysis → Credit assistant**, expand **Suggested follow-up questions**,
then select a question to fill
**Question draft**, edit it if needed, then **Send question**. An existing draft is
kept when another suggestion is selected. Free-text chat remains available. Answers
receive the current saved review and its evidence, with opinions distinguished from
financial facts. Selecting a suggestion does not send it or enable recalculation.

Saved analyses without questions offer **Generate follow-up questions**;
**Regenerate questions** explicitly requests a new set. Calculation-only generation
is available when no review exists. A new review gets questions based on the combined
analysis. Credentials are needed for generation/replies; saved suggestions remain
readable without credentials. Reading pages and switching assistant views do not
generate questions. Review-specific questions and drafts refresh when the analysis changes.

Question sidecars live under `data/runtime/portfolio/follow_up_questions/`, separately
from frozen assessment/review snapshots. Their cache identity includes the complete
input context, model and prompt version. **Question generation usage** shows the saved
request/token counts. Generation is also attributed to its own observability activity.

For an opt-in quality review of saved analyses, run:

```bash
uv run --locked python scripts/evaluate_follow_up_questions.py --live \
  --run-id YOUR_SAVED_ASSESSMENT_ID --output /tmp/follow-up-quality.json
```

This makes billable model requests for each saved review version and writes the
contexts, generated questions and a relevance/grounding/usefulness scoring rubric.
Repeat `--run-id` for varied borrowers, and compare review versions with identical
calculations. A human must fill in the scores; successful generation alone does
not demonstrate quality. Routine automated tests use controlled models and stay offline.

## Connected portfolio

1. Choose a reporting period and information cutoff. **Latest available per borrower**
   uses each borrower's latest source period at or before the cutoff. The bundled
   financials cover 2025; the table shows each actual period, including mixed periods.
2. Choose a borrower and **Run selected assessment**, or **Assess all borrowers**.
   The all-borrower action includes every registered borrower regardless of search
   filters. Missing period inputs stay missing; another quarter is never substituted.
   Enable **Include agent reviews** before requesting the assessment to run the
   bullish, bearish and recommendation agents for each new assessment. It is off
   by default and requires `OPENAI_API_KEY`. Expand **Agent review settings** to
   provide the question, criteria and constraints shared by the requested borrowers.
3. Search/filter the table or click a cell to inspect saved calculations, source
   references, headroom, trends and verification. Reading the page does not run work.
4. In **Agent analysis**, supply a question, criteria and any decision constraints,
   then **Run agent review**. Set `OPENAI_API_KEY` in the environment or root `.env`;
   `LLM_MODEL` overrides the existing default model. This explicitly invokes the real
   bullish, bearish and recommendation agents and incurs provider usage.
5. Review the main arguments, synthesis, full rationales and evidence limitations.
   Reviews use the exact saved assessment without recalculation. A new assessment
   requires a new review; earlier records remain stored.

The input data is synthetic; calculations are real service outputs. Portfolio and
Borrower analysis enable the bundled Logistic Regression forecast by default.
Borrower analysis also offers Off and Stub. News remains explicitly unavailable through the
current provider. Source availability warnings and incomplete/waived/inactive states
are preserved. A failed calculation skips its review. A failed review preserves its
assessment and does not stop the remaining borrowers. The run outcomes show assessment
and agent-review results separately; saved reviews stay linked to their exact run.

Working financial inputs, analytics and complete assessment/review snapshots are
stored under ignored `data/runtime/portfolio/`. The seed database is copied only if
the working database does not exist. Reloading the browser or restarting the app
retains saved results. No document downloads or extraction are triggered by this page.

## Connected borrower analysis

1. Select a borrower in Portfolio and click **Open borrower analysis**, or use the
   sidebar. Use **Assessment settings** for the reporting period, prediction mode and
   saved assessment version. The toolbar keeps the assessment action, source documents,
   information cutoff and Assistant toggle together.
   Saved results load without calculations or model calls; **Run assessment** saves
   a new version. A saved run's actual cutoff remains visible when it is earlier
   than the selected cutoff. All catalog borrowers remain selectable, including
   those with missing financial inputs.
   An older assessment with ML disabled offers **Run assessment with ML**, which
   preserves its inputs in a new version. Run the credit review again on that version
   to include the forecast; saved older reviews retain their original evidence.
2. Inspect **Overview**, **Calculations** and **Credit analysis**. Calculations show
   saved input metrics, source references, contractual formulas/adjustments,
   thresholds, headroom, verification and optional forecasts. Credit reviews run
   the three real agents on the selected assessment. New context is retained as
   decision constraints/assumptions, without inventing evidence sources.
3. Use the assistant panel to discuss the saved assessment. **Expand**, **Back to
   analysis**, **Hide** and **Assistant** preserve the same conversation. Each
   borrower/assessment version has its own session-owned conversation. Credentials
   are required for replies. Questions read saved inputs/results by default;
   **Allow recalculation for this question** lets the existing tools save a new run,
   select it and require fresh validation. Forecast requests also need a prediction
   mode. Browser refresh may clear chat memory.
4. In **Analyst handoff**, complete the three validation checks and record notes.
   Structured verification errors block validation. Missing or conflicting data
   require explicit exceptions. A new assessment or credit review needs new validation.
5. Add a flag with category, severity, explanation and proposed action. Write your
   observations, then **Save draft** or **Send to risk manager**. A breach needs a
   flag for that version or an explained triage decision. Submissions freeze the
   exact assessment/review IDs, source snapshots, flags, validation and analyst text.
6. Open **Risk review** to inspect submitted versions, agent reviews and saved manager
   feedback. **Analyst handoff** also shows further-analysis requests. Context-only
   requests can run their specified review; correction requests require recalculation,
   validation and resubmission before you select the new submission and **Submit response**.
7. Expand **Recalculate with revised financial inputs**, select metrics, change
   their values, provide a reason and **Recalculate**. Clear a value to mark it
   missing. Revisions retain earlier revised metrics and leave the source database
   unchanged. The new run needs fresh validation and does not close existing flags.
8. Select a prior **Assessment version** in **Assessment settings** to inspect old results, or use **History**
   for the version table and expandable saved reviews, lineage, validation events,
   drafts and immutable submissions.

Assessment/review snapshots remain in `data/runtime/portfolio/portfolio.sqlite3`;
analyst decisions and submissions live in adjacent `workflow.sqlite3`, separately
from financial and analytics databases. Both survive app restarts and navigation resets.
Logistic Regression requires the optional ML dependencies and bundled model artifact;
its synthetic training limitations remain visible.

## Connected documents and data

1. Open **Documents & data** or **Source documents** from Borrower analysis. The page
   shows real catalog records, URLs/dates, local HTML/Markdown, extraction state,
   completed sections and failures. Reading the inventory runs no downloads or agents.
2. Choose the borrower and a source view. **Borrower and unlinked sources** includes
   the public catalog until explicitly linked. Public issuers are separate from the
   synthetic portfolio: names and tickers never assign a borrower automatically.
3. In **Register & link**, register an HTML URL, issuer/title/date and explicit
   borrower links, or edit links for an existing document. Bundled CSVs stay unchanged.
   Unsupported formats, including PDF, remain visible with an explicit issue.
4. In **Inventory & processing**, select documents and **Fetch selected**. Configure
   `SEC_USER_AGENT` in `.env` or enter the identifying name/organization and email.
   Existing nonempty HTML is reused; failed downloads are recorded individually.
5. Set `OPENAI_API_KEY` and **Process selected** to run the existing cleaning,
   conversion and extraction pipeline. Processing may fetch missing HTML. Missing,
   stale or failed sources can be processed in a batch; retries reuse completed
   sections. **Force reprocess selected** explicitly reruns every section.
6. Inspect saved facts, source text, citations, cache use and section counts. These
   are extracted evidence; update financial inputs or contractual definitions
   explicitly before expecting different calculation results. New linked sources
   mark older assessments as needing review and block their validation/submission.
   Reassess explicitly after reviewing changes; submitted snapshots stay frozen.
7. In **Rebuild working data**, rebuild the lexical index from all local Markdown
   and verify retrieval with **Search evidence**. Or recreate an entire working
   financial, extraction or analytics database. The target and source are shown.
   A backup is retained before a replacement is built, checked and atomically installed.
   Financial recreation reloads the source CSV; extraction restores its recovery
   archive, created by processing; analytics restores retained assessment snapshots.
   Missing/invalid sources leave the current database in place. Workflow records,
   flags and submitted reports are preserved.
8. Keep the page open during operations. Progress shows the current document,
   stage, document counts and sections. **Operation history** persists outcomes;
   unfinished records appear interrupted after restart. Retry explicitly to reuse
   cached work. A process-local lock prevents overlapping document/data operations.

Catalog metadata, links and operation records live in `workflow.sqlite3`. Generated
`documents/catalog.csv` and `documents/extractions.sqlite3` live below
`data/runtime/portfolio/`, with an adjacent extraction recovery archive. Downloaded
HTML and converted Markdown reuse `data/cache/sec/`. Database backups live in
`data/runtime/portfolio/backups/`. Navigation resets retain these connected records.

## Connected risk review

1. Open **Risk review**, choose the period/cutoff and select a borrower or click a
   queue cell/row. Metrics use the same saved calculations as Portfolio. The queue
   includes flagged borrowers, submitted reports and untriaged breaches; waived,
   not-tested and incomplete compliance states remain distinct.
2. Select a **Submitted version**. The credit analysis snapshot appears before the
   analyst handoff and manager form. Inspect calculations/evidence and compare saved
   credit-review versions. Submitted text and its original analysis stay frozen.
3. **Save comment** for observations, or add a recommendation and **Mark reviewed**.
   Manager decisions bind the submission and current credit-review IDs. New source
   changes, calculations or submissions require fresh review. **Resolve selected flags**
   closes only the explicitly selected flags covered by that submission; compliance
   remains unchanged. Feedback appears on Borrower analysis.
4. Expand **Request another analysis**. Choose a context-only review or a correction
   request, supply the question/context and known source/date, and set the review
   cutoff. Unsourced claims remain assumptions; later information needs a later cutoff.
   **Send analysis request** saves work for the analyst. **Run context-only review**
   immediately invokes the three agents on the exact saved calculations and shared
   additional context; it requires `OPENAI_API_KEY`. Previous reviews remain visible.
5. Context results become response-ready only when the review completes; incomplete
   versions are saved for explicit retry. Correction requests return to the analyst
   for recalculation, fresh validation, resubmission and a response linked to the new
   submission. Use **Open borrower analysis** to retain the borrower and reporting dates.
6. Inspect the response and **Accept response**, then record the manager recommendation
   and complete review. Open requests block completion. Cancel obsolete requests with
   a recorded reason. All requests, responses and decisions survive app restart.

## Connected board reports

1. Open **Board report**, choose the period/cutoff and **Generate report draft**.
   The saved draft includes all open flags in scope, unresolved older cases with actual
   assessment dates, untriaged breaches, pending submissions and missing-analysis counts.
   Portfolio metrics use borrower counts; borrower debt is never treated as portfolio exposure.
2. Inspect the complete flagged register and per-borrower source snapshots, risk/mitigants,
   bull/bear conclusions, analyst observations, manager recommendations and outstanding
   actions. Missing analysis or decisions remain explicitly pending.
3. Edit the executive summary and board-facing recommendations. **Save report draft**
   creates a new saved version. Board-facing edits do not change manager sign-off.
4. If underlying cases change, **Refresh draft sources** and inspect the updated register
   before finalization. Finalization refuses stale sources, preventing new flags or
   pending cases from being silently omitted. Missing recommendations may remain pending.
5. **Finalize report** freezes its complete content and sources. Later calculations,
   flags, requests or decisions do not rewrite it. Use the **Report** selector or
   `?report_id=...` to open a saved report directly. Final reports cannot be edited;
   generate a new report for subsequent changes.

Manager notes, requests and board report versions live in the existing
`data/runtime/portfolio/workflow.sqlite3`. **Reset navigation** changes the view
without deleting any saved work. Background processing, external notifications,
authentication and PDF export remain outside this POC.

## Feedback to collect

- Can an analyst find a borrower and inspect the reasons for its current status?
- Are real results, missing inputs and saved review versions clear in Portfolio?
- Does the saved validation and report inbox communicate the analyst handoff?
- Does the chat leave enough room for analysis, and can the manager find a response?
- Does the board report contain the explanation, risk analysis and recommendation needed?
