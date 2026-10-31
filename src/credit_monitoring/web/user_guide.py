"""Task-oriented help shared by the guide page and inline workspace help."""

import streamlit as st

TOPICS = {
    "Get started": """
1. Open **Portfolio**, select a borrower and choose a reporting period and
information cutoff. The cutoff must be on or after the period. **Latest available
per borrower** can show different actual periods for different borrowers. The bundled
financials currently cover 2025; use the periods available in your loaded data.
2. Leave **Include agent reviews** off for a calculation-only start, then choose
**Run selected assessment**. A new saved assessment appears, including any missing inputs.
3. Choose **Open borrower analysis**. Read **Overview** and **Calculations** to inspect
inputs, sources, contractual terms, actual values, thresholds, headroom and verification.
The **Borrower directory** at the top lets you search and click a borrower to open its
analysis below, including borrowers without a saved assessment.
4. Use **Assessment settings** to change the reporting period, prediction mode or saved version.
Optionally use **Credit analysis → Run agent review** to run bullish, bearish and
recommendation agents, followed by an agent that suggests follow-up questions.
5. In **Analyst handoff**, complete the three checks, record exceptions, then
**Mark validated**. Resolve structured verification errors before validating.
6. Add a flag when needed. A breach requires a flag for this version or an explained
**Breach triage decision**. Write observations, then **Save draft** or **Send to risk manager**.
7. Open **Risk review**, select the borrower and **Submitted version**, and inspect the
frozen analyst handoff. Manager comments, review decisions and requests are saved there.

Calculations work without model credentials. Reviews, question generation and assistant
replies require the operator to configure OPENAI_API_KEY and incur provider usage.
""",
    "Portfolio and dates": """
1. Search by name or borrower ID and use the compliance/sector filters.
Click a table cell or use **Select borrower** to inspect saved results.
2. Choose **Reporting period** and **Information cutoff**. Each row shows its actual
source period. Missing quarter inputs remain missing; another quarter is not substituted.
3. Choose **Run selected assessment**, or **Assess all borrowers** for the entire
registered catalog, including borrowers hidden by filters.
4. Enable **Include agent reviews** only when you want model reviews and generated
follow-up questions for newly assessed borrowers. **Agent review settings** supplies
the shared question, credit criteria and constraints.

Opening or filtering a page does not run assessments or agents. A new run saves a
new version; earlier results remain available.
""",
    "Read an assessment": """
1. Use **Overview** for saved covenant status and **Calculations** for
the underlying inputs, source references, formulas, contractual adjustments and thresholds.
2. Compare actual values with their threshold/operator. Headroom measures the margin
to the limit in the covenant's own units; negative headroom can indicate a breach.
3. Read verification and data limitations. **Incomplete**, **unresolved**, **unsupported**,
**waived** and **not tested** are separate outcomes, not automatic passes or breaches.
4. Review any reported rather than independently calculated values and unknown source
availability dates. Structured verification does not verify every generated statement.

Inputs and model training data are synthetic. The analyst remains responsible for decisions.
""",
    "Credit reviews and forecasts": """
1. In **Credit analysis**, enter a **Credit review question**,
**Credit criteria**, and any **Additional context / constraints**, then **Run agent review**.
The bullish, bearish and recommendation agents use the exact selected saved assessment.
2. Read each argument, counterevidence, rationale, evidence reference, confidence and
limitation. Additional context may be an assumption; it does not become a new source fact.
3. Review the generated follow-up questions in the assistant. A separate read-only agent
uses both calculations and the risk agents' outputs to propose questions specific to them.
4. **Assessment settings → Prediction mode** supports **Off**, **Stub**, and
**Logistic Regression**. The connected workspace defaults to the bundled trained model.
Stub supplies no probability.
5. If a saved assessment has ML off, use **Run assessment with ML** to create a new version,
then rerun the review. Old reviews keep their original evidence.

Current covenant compliance and next-quarter forecasts are different. Synthetic training
does not establish real-world performance. Reviews plus follow-up generation incur provider
usage. A new review requires fresh analyst validation.
""",
    "Ask the assistant": """
1. In **Borrower analysis**, select a saved assessment and enable **Assistant**.
Use **Expand**, **Back to analysis**, or **Hide** to adjust the workspace; the conversation
belongs to this borrower and assessment version in your browser session.
2. Expand **Suggested follow-up questions**. They are written by an agent from the saved
calculations and matching bullish, bearish and recommendation analyses, not a question bank.
3. Select a question to fill the editable **Question draft**, then choose **Send question**.
You can edit it first. Selecting a suggestion does not call a model or change the analysis.
You can also type any question into **Ask about this borrower…**.
4. Older analyses may offer **Generate follow-up questions**; **Regenerate questions**
requests a new set. Generation requires credentials. Saved questions remain readable without them.
5. Questions read saved results by default. **Allow recalculation for this question**
permits a new saved version and requires fresh validation; forecasts need a prediction mode.

The assistant explains the selected borrower's saved evidence and risk analysis. It cannot
research arbitrary filings or calculate arbitrary other periods in this chat. Change the
selection for a different borrower/period. **Clear conversation** starts fresh; browser
refresh may clear conversation memory. Save report drafts before navigating away.
""",
    "Validate, flag and submit": """
1. In **Analyst handoff**, check the financial inputs/sources,
applied terms/calculations, and analysis/exceptions. Record **Validation notes / exceptions**,
then **Mark validated**. Missing/conflicting data require explicit exceptions; structured
verification errors block validation. Changed sources require reassessment.
2. Under **Flag for risk review**, choose category/severity, explain the concern and
proposed action, then **Add flag**. Flags are saved for the exact assessment version.
3. Write **Observations and proposed recommendation**. Use **Save draft** before leaving
unfinished work. For a breach, add a flag for this version or explain the triage decision.
4. Choose **Send to risk manager**. The submitted text, validation, flags, source snapshot,
assessment and review IDs are frozen. Later analysis does not rewrite that submission.
5. In **Risk review**, select the borrower/submitted version. Managers can save comments,
recommendations, review decisions and further analysis requests. Feedback returns to the analyst.

A new assessment or credit review needs fresh validation. Open requests and source changes
can block manager completion; inspect the message and resolve the named issue.
""",
    "Revisions and history": """
1. Expand **Recalculate with revised financial inputs**, select metrics,
enter corrected values and a reason, then **Recalculate**. Clear a value to record it missing.
2. A new version retains the earlier source database and prior submitted snapshots.
It needs fresh validation and a new credit review; existing flags do not close automatically.
3. Choose **Assessment version** in **Assessment settings** to inspect an earlier run.
Use the **History** table for saved versions and its expandable records for reviews,
lineage, validation events, drafts and submissions.
4. After a new credit review, suggestions use the new analysis; previous opinions in the
conversation are not the current recommendation. Generation does not itself invalidate validation.
""",
    "Documents, manager and board workflows": """
The workspace pages are connected and save their records locally.
The financial inputs are synthetic; the original app's separate benchmark page is a mock.

- **Documents & data:** register/link source URLs, fetch/process selected documents,
inspect extraction status and sources, and search indexed evidence. These actions run only
when requested. Processing can use model calls; SEC downloads need operator configuration.
**Documents processed at once** defaults to four. Reduce it to one for sequential processing;
completed files and saved sections are reused on retry.
Source changes can mark assessments as needing review. Inspect before reassessing.
- **Risk review:** inspect submitted versions, compare risk-agent analyses, save comments
and recommendations, resolve selected flags, and request another analysis. Context-only
reviews run on saved calculations; correction requests return to the analyst for a new run.
- **Board report:** generate a saved draft from the reporting scope, inspect flags and
pending cases, edit the executive summary and board recommendations, and save the draft.
Refresh stale draft sources before **Finalize report**. Final reports freeze content and sources.

Saved assessments, flags, reports and generated questions survive app restarts. **Reset navigation**
keeps saved records. Unsaved form edits and session-owned chats do not have that persistence.
""",
    "Troubleshooting and glossary": """
- **No saved assessment / missing financials:** check borrower,
period and cutoff; choose an available period or record the missing-data limitation.
- **Assistant, reviews or generation unavailable:** ask the operator to configure OPENAI_API_KEY.
Never paste credentials into chat. Saved results remain readable. Failed question generation
does not discard the analysis; use **Generate follow-up questions** to retry.
- **Forecast unavailable:** inspect prediction mode and saved ML status. Stub has no forecast.
Logistic Regression needs installed ML dependencies and the bundled compatible artifact.
- **Cannot validate or submit:** resolve verification errors, complete the checks, record
exceptions, write report text and add breach flags or triage as required by the displayed message.
- **Validation needed again:** new assessments and credit reviews need fresh validation.

**Borrower:** the entity being assessed. **Covenant:** a contractual financial test.
**Headroom:** margin to the test's limit. **Reporting period:** date the financials describe.
**Information cutoff:** latest information date allowed for the analysis; unknown publication
dates remain a limitation. **Assessment:** saved calculation results. **Credit review:** saved
bullish, bearish and recommendation analysis. **Forecast:** model output for a future period.
**Validation:** the analyst's recorded review of a particular assessment and credit review.
""",
}

# Widget values disappear when their page is absent. Keep only working selections,
# not unfinished forms, while the user reads the full guide.
SELECTION_KEYS = (
    "portfolio_borrower",
    "portfolio_period",
    "portfolio_cutoff",
    "portfolio_search",
    "portfolio_status_filter",
    "portfolio_sector_filter",
    "portfolio_include_reviews",
    "analysis_borrower",
    "analysis_period",
    "analysis_cutoff",
    "analysis_prediction",
    "analysis_version",
    "analysis_show_chat",
    "analysis_directory_search",
    "risk_borrower",
    "risk_period",
    "risk_cutoff",
    "risk_queue_filter",
    "board_report_selection",
    "board_period",
    "board_cutoff",
    "documents_borrower",
    "documents_view",
)


def remember_navigation() -> None:
    page = st.session_state.get("preview_page", "Portfolio")
    previous = st.session_state.get("guide_active_page", "Portfolio")
    if page == "User guide" and previous != page:
        st.session_state.guide_previous_page = previous
        st.session_state.guide_selections = {
            key: st.session_state[key] for key in SELECTION_KEYS if key in st.session_state
        }
    elif previous == "User guide" and page == st.session_state.get("guide_previous_page"):
        for key, value in st.session_state.get("guide_selections", {}).items():
            st.session_state[key] = value
    st.session_state.guide_active_page = page


def navigate(page: str) -> None:
    st.session_state._preview_next_page = page
    st.rerun()


def render_help(topic: str, label: str) -> None:
    with st.expander(label):
        st.markdown(TOPICS[topic])


def render_invitation() -> None:
    if st.session_state.get("guide_invitation_dismissed"):
        return
    with st.container(border=True):
        st.markdown("**New here? Start with your first assessment**")
        start, dismiss = st.columns(2)
        if start.button("Open user guide", key="guide_start"):
            navigate("User guide")
        dismiss.button(
            "Dismiss",
            key="guide_dismiss",
            on_click=lambda: st.session_state.update(guide_invitation_dismissed=True),
        )


def render_user_guide() -> None:
    st.title("User guide")
    st.caption("From your first assessment to a saved analyst handoff and manager review.")
    st.info(
        "Save report drafts before leaving a working page. "
        "Unsubmitted forms are not saved automatically."
    )
    topic = st.selectbox("Guide topic", list(TOPICS), key="guide_topic")
    with st.container(width=850):
        st.subheader(topic)
        st.markdown(TOPICS[topic])
    previous = st.session_state.get("guide_previous_page", "Portfolio")
    if st.button("Back to previous page", key="guide_back"):
        navigate(previous)
    columns = st.columns(3)
    for column, page in zip(
        columns, ("Portfolio", "Borrower analysis", "Risk review"), strict=True
    ):
        if column.button(f"Open {page}", key=f"guide_open_{page}"):
            navigate(page)
