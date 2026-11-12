# V3 workspace

Run `make preview-v3` and open the printed Streamlit URL. For a parallel instance,
append `--server.port 8503` to the Streamlit command in that Make target.

V3 lives in `src/credit_monitoring/web_v3/`. The original workspace and V2 keep
their own entry points. V3 shares `data/runtime/portfolio/` and the SEC cache:
assessments, documents, flags, submissions, decisions and reports created here
are visible in the other apps. Launch commands and Docker defaults are unchanged.

## Analyst work

1. Choose the reporting period and information cutoff in the sidebar. The queue
   defaults to **Needs action**. Counts overlap; use **All borrowers** for the full list
   and expand the comparison table for portfolio-wide inspection.
2. Follow a borrower's action or choose **Open borrower**. Evidence readiness,
   covenant compliance, and review progress appear separately. The next-action
   panel identifies the recommended task; the progress checklist shows the handoff.
3. In **Documents**, configure required document types for this borrower and period.
   Explicitly select linked catalog documents for each type. An absent checklist
   means **Requirements not configured**; saving no types means no documents are required.
   Old agreements may be reused explicitly. Names, dates, and tickers never create links.
4. Use **Add or link sources** to register an HTML URL or discover existing sources.
   **Process selected documents** fetches missing HTML and reuses completed sections.
   Failed work can be retried; fetch and force-reprocessing are advanced options.
   Keep the page open while processing. Inspect the source text and extracted facts.
5. Return to the borrower and **Run covenant assessment**. Extraction supplies
   evidence; it does not automatically change financial inputs or calculation rules.
   Use **Evidence → Revise financial inputs and recalculate** for explicit revisions.
6. **Generate AI credit analysis** is optional. It reads the selected saved version,
   incurs model usage, and invalidates earlier validation for that assessment.
7. **Review and submit findings** contains manager requests, findings, breach flags
   or triage, the three human review checks, validation notes, and a submission preview.
   Use **Save draft** for durable findings. Unsaved edits survive session navigation.
8. Submit after resolving the listed blockers. Checklist gaps are warnings only;
   existing verification, source-change, validation, and breach-triage rules still apply.
   Submissions freeze their evidence and analysis.

## Assistant

**Ask credit assistant** opens a wide reading page for the selected saved version.
Suggested questions populate the same editable composer; they do not send immediately
or overwrite a nonempty draft. Conversations are isolated by assessment version and
last for the browser session. Answers and their actual citations retain their original
wording. Recalculation is off unless explicitly enabled for a question; a resulting
new assessment requires fresh validation.

## Risk manager

The queue includes flags, untriaged breaches, submissions, and outstanding requests.
It defaults to **Needs attention**, ordered by severity, outstanding request due date,
then borrower name. **Open case** opens a separate page; **Back to risk queue** preserves
filters and **Next case** follows the filtered order.

Inspect analyst findings, covenants, flags, exceptions, and requests before recording
a decision. Current checklist readiness is labeled separately from frozen submitted
evidence. Cases without submissions remain inspectable but cannot be signed off.

**Request analyst follow-up** saves an assigned task. Context requests require a
supplementary AI analysis; corrections require a new assessment, validation, and
submission. **Run supplementary AI analysis** creates and executes a context request
directly. Inspect its saved response and **Accept response** before completing review.
Outstanding requests, stale sources, newer work, and reviews outside the selected cutoff
retain their existing completion restrictions.

## Reports and settings

**Board reports** generates drafts, edits summaries and borrower recommendations,
refreshes source snapshots, and finalizes frozen versions. Saved versions remain
selectable; `?report_id=...` opens a report directly. Refresh changed sources and inspect
them before finalization.

**Settings** controls prediction mode for new assessments, SEC download identity,
document concurrency, and explicit data maintenance. AI needs operator-configured
`OPENAI_API_KEY`; SEC fetching needs `SEC_USER_AGENT` or a session download identity.
HTML processing is supported. PDF and local file uploads are deferred.

V3 adds only the `v3_document_checklists` table to shared workflow storage. It does not
replace existing records or change the calculation and decision services.
