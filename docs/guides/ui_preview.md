# Workspace walkthrough

Install the environment using the [README](../../README.md#run-the-app), then run
`make preview`. Open the Streamlit URL printed in the terminal. For a second instance:

```bash
uv run --locked --extra ml streamlit run src/credit_monitoring/web/preview.py --server.port 8502
```

Use the sidebar for **Portfolio**, **Risk review**, **Board reports**, and **Documents**.
**Help** and **Settings** are below the main navigation. Contextual Help popovers explain
controls. Borrower observations and validation edits survive in-session navigation;
**Save draft** retains observations after restart.

## Assess a borrower

1. In **Portfolio**, choose the reporting period and information cutoff.
   **Latest available per borrower** selects each borrower's latest eligible period.
2. Select a table row or use the **Borrower** picker, then choose **Open borrower**.
3. Choose **Run assessment** in the borrower workspace. The header shows the reporting
   period, cutoff and saved version. Use **Run new assessment** to create another version.
4. **Overview** shows covenant results, trends, forecast and a concise AI recommendation.
   **Evidence** contains calculations, inputs, applied terms, source references and verification.
   **Review and submit** prepares the handoff; **History** contains saved versions and submissions.
5. For an optional AI review, expand **AI review** in Overview, provide a question,
   criteria and constraints, then **Generate AI review**. Supporting arguments are expandable.
   Reviews require `OPENAI_API_KEY` and incur provider usage.
6. Use **Back to portfolio** to return to your filters. Portfolio-wide assessments are
   under **Batch actions** and include every registered borrower regardless of filters.
   **Include agent reviews** optionally adds reviews to that batch.

The main workspace uses the bundled synthetic-trained Logistic Regression forecast by
default. **Off** and **Stub** are available under **Settings → Prediction mode**. An older assessment without ML can be
updated with **Run assessment with ML**, followed by a new agent review. Calculations,
forecasts, and advisory opinions are shown separately.

Browsing does not launch work. New calculations and reviews create saved versions.
A failed review preserves its assessment and does not stop other borrowers.

## Ask questions and revise inputs

Enable **Ask assistant** to open the assistant alongside results and discuss the selected saved analysis. Suggested follow-up
questions fill the editable **Question draft**; **Send question** submits it. A review
generates up to three questions, and older analyses offer **Generate follow-up questions**.
Generation and replies need model credentials; saved questions are reused when browsing.

Each borrower/assessment version has its own conversation. Browser refresh may clear
chat memory. **Allow recalculation for this question** explicitly permits a new run.

For manual changes, open **Evidence** and expand **Recalculate with revised financial inputs**, select metrics,
enter values and a reason, then **Recalculate**. Clearing a value marks it missing.
Revisions preserve earlier versions and need fresh validation.

## Validate and submit

1. In **Review and submit**, record observations, address risks, and complete the
   three validation checks and notes. Structured
   errors block validation; missing or conflicting evidence needs an explicit exception.
2. Add flags with severity, explanation, and proposed action. A breach needs a flag
   for that version or an explained triage decision.
3. Write observations, then **Save draft** or **Send to risk manager**. A submission
   freezes its assessment, review, sources, flags, validation, and text.

New calculations, reviews, or linked source changes require fresh review and validation.
Use **History** to inspect versions and submissions.

## Manage documents and data

1. Open **Documents** and choose a borrower/source view. Public issuers are
   separate from synthetic borrowers; link sources explicitly in **Register & link**.
2. Register an HTML URL and metadata, or select existing sources. PDF is unsupported.
3. **Fetch selected** downloads missing HTML using `SEC_USER_AGENT`.
4. **Process selected** cleans, converts, and extracts using `OPENAI_API_KEY`.
   **Advanced processing options → Documents processed at once** defaults to four; select one for sequential work.
   Retries reuse completed sections; **Force reprocess selected** reruns all sections.
5. Inspect source text, facts, citations, and failures. Extraction does not update
   financial inputs or contractual calculation rules automatically.
6. Use **Settings → Working data maintenance** to rebuild the lexical index or a database. The page
   shows the target and recovery source; replacements retain a backup. Missing or
   invalid recovery sources leave the working database in place.

Keep the page open during processing. **Operation history** retains outcomes and shows
interrupted work after restart. New linked sources mark older assessments for review;
submitted snapshots remain frozen.

## Complete risk review

1. In **Risk review**, select the borrower and **Submitted version**. Review the saved
   evidence, credit analysis, and analyst observations.
2. **Save comment**, add a recommendation, then **Mark reviewed**. Resolve only the
   selected flags covered by that submission; closing flags does not change compliance.
3. Use **Request another analysis** for new context or a correction. A context-only
   review reuses the saved calculations; a correction needs recalculation, validation,
   and resubmission by the analyst.
4. Inspect and **Accept response**, then complete review. Open requests block completion;
   obsolete requests can be canceled with a recorded reason.

The selected information cutoff also limits the credit reviews shown. If a supplementary
review uses later information, advance **Information cutoff** and inspect that review
before marking the case reviewed. Saving a comment keeps it linked to the visible review.

## Prepare a board report

1. In **Board reports**, choose dates and **Generate report draft**. The report includes
   open flags, unresolved older cases, untriaged breaches, and pending work.
2. Review the register, source snapshots, analyst observations, and manager recommendations.
   Edit the executive summary and recommendations, then **Save report draft**.
3. If cases change, **Refresh draft sources**. Stale sources block finalization.
4. **Finalize report** freezes the content. Open saved reports with the selector or
   `?report_id=...`; create a new report for later changes.

Portfolio counts represent borrowers; borrower debt is not portfolio exposure.
Missing analysis and decisions remain pending.

## Storage and troubleshooting

Saved assessments and workflow records live under ignored `data/runtime/portfolio/`;
source downloads use `data/cache/sec/`. Reloading, restarting, and **Reset navigation**
retain saved work. The POC has no authentication, notifications, or PDF export.

If an update causes an import error, stop Streamlit with **Ctrl+C** and rerun
`make preview`. Browser refresh alone may retain old Python modules.

For optional question-quality evaluation, see [credit reviews](credit_review.md#validation-and-model-evaluation).
