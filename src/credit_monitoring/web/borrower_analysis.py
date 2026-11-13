"""Connected borrower workspace with versioned calculations and a durable analyst handoff."""

import os
from dataclasses import replace
from datetime import date
from html import escape

import dotenv
import streamlit as st

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.borrower_workflow import (
    BorrowerWorkflow,
    SavedAssessmentChat,
    SavedFinancials,
)
from credit_monitoring.config.settings import DEFAULT_APP_PREDICTION_MODE
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult
from credit_monitoring.domain.financials import FINANCIAL_METRICS
from credit_monitoring.persistence.workflow_repository import WorkflowRepository
from credit_monitoring.web import portfolio as portfolio_page
from credit_monitoring.web.assessment import render_answer, render_prediction
from credit_monitoring.web.borrower_views import (
    render_calculation_tables,
    render_covenant_table,
    render_history_table,
    render_saved_trend,
    render_status,
    render_summary_metrics,
)
from credit_monitoring.web.navigation import navigate
from credit_monitoring.web.telemetry import with_web_session
from credit_monitoring.web.user_guide import TOPICS
from credit_monitoring.web.workspace import ask_about_assessment


def get_workflow() -> BorrowerWorkflow:
    dotenv.load_dotenv(portfolio_page.DEFAULT_DATA_ROOT.parent / ".env")
    portfolio = portfolio_page.get_portfolio_service(
        str(portfolio_page.DEFAULT_DATA_ROOT),
        str(portfolio_page.DEFAULT_WORKING_DIR),
        os.getenv("LLM_MODEL") or DEFAULT_MODEL,
    )
    return BorrowerWorkflow(
        portfolio,
        WorkflowRepository(portfolio_page.DEFAULT_WORKING_DIR / "workflow.sqlite3"),
        portfolio_page.DEFAULT_DATA_ROOT,
    )


def select_borrower() -> None:
    st.session_state.portfolio_borrower = st.session_state.analysis_borrower
    st.session_state.preview_selected_borrower = st.session_state.analysis_borrower
    st.session_state.analysis_directory_revision = (
        st.session_state.get("analysis_directory_revision", 0) + 1
    )


def select_review_section() -> None:
    st.session_state.analysis_section = "Review and submit"


def select_new_run(assessment: RiskAssessment) -> None:
    st.session_state._analysis_next_run = assessment.assessment_run_id
    st.rerun()


def action(callback, message: str) -> None:
    try:
        callback()
    except ValueError as error:
        st.warning(str(error))
    except Exception as error:
        st.error(f"Action failed ({type(error).__name__}). Earlier saved records are retained.")
    else:
        st.toast(message)
        st.rerun()


def render_flags(workflow: BorrowerWorkflow, borrower_id: str) -> None:
    flags = workflow.repository.flags(borrower_id)
    if not flags:
        st.caption("No open analyst flags.")
    for flag in flags:
        item = flag["payload"]
        with st.container(border=True):
            st.markdown(f"**{item['severity']} · {item['category']} · {item['state']}**")
            st.write(item["explanation"])
            st.caption(item["action"] or "No proposed action recorded.")
            st.caption(f"Assessment {flag['run_id']} · {flag['created_at']}")


def render_handoff(workflow: BorrowerWorkflow, assessment: RiskAssessment) -> None:
    from credit_monitoring.application.manager_workflow import ManagerWorkflow
    from credit_monitoring.web.review_requests import render_manager_feedback

    render_manager_feedback(ManagerWorkflow(workflow), assessment.borrower_id)
    run_id = assessment.assessment_run_id
    validated = workflow.validation(run_id)
    validation = validated["payload"] if validated else {}
    drafts = workflow.repository.events(run_id, "draft")
    submissions = [
        item
        for item in workflow.repository.submissions(assessment.borrower_id)
        if item["run_id"] == run_id
    ]
    latest = max(drafts + submissions, key=lambda item: item["created_at"], default={})
    previous = latest.get("payload", {})
    st.subheader("1. Record your findings")
    author = st.text_input(
        "Analyst name (optional)",
        value=previous.get("analyst", validation.get("analyst", "")),
        key=f"analysis_report_author_{run_id}",
    )
    report = st.text_area(
        "Observations and proposed recommendation",
        value=previous.get("text", ""),
        key=f"analysis_report_text_{run_id}",
        height=150,
    )
    st.subheader("2. Address risks and exceptions")
    has_breach = any(result.compliance_status == "breach" for result in assessment.results)
    triage = (
        st.text_area(
            "Breach triage decision (required if no flag for this version)",
            value=previous.get("triage", ""),
            key=f"analysis_triage_{run_id}",
            help="For a breach, add a flag for this version or explain your triage decision.",
        )
        if has_breach
        else previous.get("triage", "")
    )
    with st.expander("Add a risk flag", expanded=has_breach):
        with st.form(f"analysis_flag_{run_id}"):
            category = st.selectbox(
                "Category", ["Covenant breach", "Data quality", "Liquidity", "Performance", "Other"]
            )
            severity = st.selectbox("Severity", ["Medium", "High", "Critical", "Low"])
            explanation = st.text_area(
                "Short explanation", key=f"analysis_flag_explanation_{run_id}"
            )
            proposed = st.text_input("Proposed action", key=f"analysis_flag_action_{run_id}")
            if st.form_submit_button("Add flag"):
                action(
                    lambda: workflow.flag(
                        run_id,
                        category=category,
                        severity=severity,
                        explanation=explanation,
                        action=proposed,
                    ),
                    "Flag saved.",
                )
    render_flags(workflow, assessment.borrower_id)
    st.subheader("3. Validate the selected version")
    st.caption("Check the evidence yourself. A new assessment or AI review needs fresh validation.")
    review = workflow.portfolio.repository.latest_review(run_id)
    check_scope = f"{run_id}_{review.review_id if review else 'no_review'}"
    checks = tuple(
        st.checkbox(label, value=bool(validated), key=f"analysis_check_{check_scope}_{index}")
        for index, label in enumerate(
            (
                "I checked the financial inputs and source references",
                "I checked the applied terms and calculations",
                "I reviewed the analysis and documented any exceptions",
            )
        )
    )
    notes = st.text_area(
        "Validation notes / exceptions",
        value=validation.get("notes", ""),
        key=f"analysis_validation_notes_{run_id}",
    )
    if not all(checks):
        st.caption("Complete all three review checks before validation.")
    if not assessment.verification.is_valid or any(
        issue.severity == "error" for issue in assessment.verification.issues
    ):
        st.caption("Resolve structured verification errors in Evidence before validation.")
    if workflow.needs_review(run_id):
        st.caption("Sources changed: reassess before validation.")
    if workflow.needs_exceptions(assessment) and not notes.strip():
        st.caption("Document the missing data and unresolved exceptions in validation notes.")
    if st.button("Mark validated", key=f"analysis_validate_{run_id}"):
        action(
            lambda: workflow.validate(run_id, checks=checks, notes=notes, analyst=author),
            "Validation saved.",
        )
    if validated:
        st.success("Validated with exceptions." if validation["with_exceptions"] else "Validated.")
    else:
        st.info("This assessment and review version need validation before submission.")
    st.subheader("4. Save or submit")
    current_flags = [
        f
        for f in workflow.repository.flags(assessment.borrower_id)
        if f["run_id"] == run_id and f["payload"]["state"] == "open"
    ]
    blockers = []
    if not report.strip():
        blockers.append("Add analyst observations.")
    if not validated:
        blockers.append("Validate this assessment and its current review.")
    if has_breach and not current_flags and not triage.strip():
        blockers.append("Flag this breach version or explain the triage decision.")
    if blockers:
        st.caption("Before submission: " + " ".join(blockers))
    changed = (
        report != previous.get("text", "")
        or author != previous.get("analyst", "")
        or triage != previous.get("triage", "")
    )
    st.caption(
        "Unsaved edits · kept during this session. Save draft to keep them after restart."
        if changed
        else "Saved draft loaded."
        if latest
        else "No saved draft yet."
    )
    save, submit = st.columns(2)
    draft_clicked = save.button("Save draft", key=f"analysis_save_{run_id}")
    submit_clicked = submit.button(
        "Send to risk manager", type="primary", key=f"analysis_submit_{run_id}"
    )
    if draft_clicked or submit_clicked:
        action(
            lambda: workflow.save_report(
                run_id, text=report, analyst=author, triage=triage, submit=submit_clicked
            ),
            "Report submitted to risk review." if submit_clicked else "Draft saved.",
        )
    if submissions:
        st.success(f"Submitted · {portfolio_page.formatted_time(submissions[0]['created_at'])}")
        st.caption("Submitted versions are frozen. Later edits do not change the handoff.")
        if st.button("Open risk review", key="analysis_open_risk"):
            st.session_state.risk_borrower = assessment.borrower_id
            st.session_state.risk_period = assessment.period_end.isoformat()
            st.session_state.risk_cutoff = assessment.information_cutoff
            navigate("Risk review")


def chat_state(assessment: RiskAssessment) -> dict:
    chats = st.session_state.setdefault("analysis_chats", {})
    return chats.setdefault(assessment.assessment_run_id, {"messages": []})


def _render_question_controls(
    workflow: BorrowerWorkflow,
    assessment: RiskAssessment,
    review: CreditReviewResult | None,
    state: dict,
    credentials: bool,
    scope: str,
) -> str | None:
    """Selection edits a draft; generation and sending are separate explicit actions."""
    service = workflow.portfolio.follow_up_service
    review_id = review.review_id if review else None
    draft_key = f"analysis_question_draft_{assessment.assessment_run_id}"
    origin = state.get("draft_origin")
    if state.pop("clear_draft", False) or (
        origin and origin != (assessment.assessment_run_id, review_id)
    ):
        state["draft"] = ""
        state["draft_origin"] = None
        st.session_state.pop(draft_key, None)
    saved = None
    if service is not None:
        try:
            saved = service.load(assessment, review)
        except ValueError as error:
            st.info(str(error))
            service = None
    if saved:
        st.caption(
            "Generated from the saved calculations and risk analysis."
            if review
            else "Generated from saved calculations; no credit review is saved for this version."
        )
        for index, suggestion in enumerate(saved.output.questions):
            if st.button(suggestion.question, key=f"analysis_suggestion_{scope}_{index}"):
                if state.get("draft", "").strip():
                    st.info(
                        "Your question draft is kept. Clear it before selecting another question."
                    )
                    st.write(suggestion.question)
                else:
                    state["draft"] = suggestion.question
                    state["draft_origin"] = (assessment.assessment_run_id, review_id)
                    st.session_state[draft_key] = suggestion.question
            st.caption(suggestion.reason)
        with st.expander("Question generation usage"):
            st.caption(
                f"{saved.usage.get('requests', 0)} requests · "
                f"{saved.usage.get('input_tokens', 0)} input tokens · "
                f"{saved.usage.get('output_tokens', 0)} output tokens · {saved.model}"
            )
    else:
        st.caption(
            "No generated questions are saved for this analysis yet. You can ask your own question."
        )
    if service is not None:
        st.caption("Generating questions makes a model request; provider usage applies.")
        if st.button(
            "Regenerate questions" if saved else "Generate follow-up questions",
            key=f"analysis_generate_{scope}",
            disabled=not credentials,
        ):
            try:
                with st.spinner("Generating questions from calculations and risk analysis…"):
                    service.generate(assessment, review, regenerate=bool(saved))
            except Exception as error:
                st.warning(
                    f"Question generation failed ({type(error).__name__}). "
                    "Saved analysis and any earlier questions are retained. Retry explicitly."
                )
            else:
                st.rerun()
    if draft_key not in st.session_state:
        st.session_state[draft_key] = state.get("draft", "")

    def remember_draft():
        state["draft"] = st.session_state[draft_key]
        state["draft_origin"] = None

    draft = st.text_area(
        "Question draft", key=draft_key, on_change=with_web_session(remember_draft), height=90
    )
    if st.button(
        "Send question",
        key=f"analysis_send_{scope}",
        disabled=not credentials or not draft.strip(),
    ):
        state["clear_draft"] = True
        return draft.strip()
    return None


def render_question_draft(
    workflow: BorrowerWorkflow,
    assessment: RiskAssessment,
    review: CreditReviewResult | None,
    state: dict,
    credentials: bool,
    scope: str,
) -> str | None:
    # Keep the existing chat input as the main interaction. Suggestions and their
    # editable draft are an optional disclosure, not a second always-visible composer.
    with st.expander("Suggested follow-up questions", expanded=bool(state.get("draft"))):
        return _render_question_controls(workflow, assessment, review, state, credentials, scope)


def render_chat(
    workflow: BorrowerWorkflow,
    assessment: RiskAssessment,
    prediction_mode: str,
    *,
    expanded: bool = False,
) -> None:
    state = chat_state(assessment)
    credentials = bool(os.getenv("OPENAI_API_KEY", "").strip())
    review = workflow.portfolio.repository.latest_review(assessment.assessment_run_id)
    st.caption(f"{assessment.borrower_id} · Assessment {assessment.assessment_run_id}")
    st.caption("Questions read saved results. Enable recalculation to create a new version.")
    if not credentials:
        st.info("Set OPENAI_API_KEY to enable the assistant.")
    with st.container(height=450):
        for message in state["messages"]:
            with st.chat_message(message["role"]):
                if "answer" in message:
                    render_answer(message["answer"])
                else:
                    st.write(message["content"])
    scope = f"{'expanded' if expanded else 'panel'}_{assessment.assessment_run_id}"
    drafted_question = render_question_draft(
        workflow, assessment, review, state, credentials, scope
    )
    allow = st.checkbox(
        "Allow recalculation for this question", key=f"analysis_chat_recalc_{scope}"
    )
    question = st.chat_input(
        "Ask about this borrower…", key=f"analysis_chat_input_{scope}", disabled=not credentials
    )
    if question or drafted_question:
        latest_review = workflow.portfolio.repository.latest_review(assessment.assessment_run_id)
        if (latest_review.review_id if latest_review else None) != (
            review.review_id if review else None
        ):
            st.warning("The risk analysis changed. Review the current suggestions before sending.")
            return
        question = question or drafted_question
        state["messages"].append({"role": "user", "content": question})
        adapter = state.get("adapter")
        try:
            if "conversation" not in state or state["conversation"].closed:
                adapter = SavedAssessmentChat(workflow, assessment)
                state["adapter"] = adapter
                state["conversation"] = CreditAssessmentAgent(
                    assessment_service=adapter, model=os.getenv("LLM_MODEL") or DEFAULT_MODEL
                ).start_conversation(borrower_id=assessment.borrower_id)
            adapter.allow_recalculation = allow
            adapter.new_assessment = None
            adapter.reason = f"Chat request: {question}"
            adapter.prediction_mode = prediction_mode
            with st.spinner("Reading assessment evidence…"):
                answer = ask_about_assessment(
                    state["conversation"], question, assessment, review=latest_review
                )
            state["messages"].append(
                {"role": "assistant", "answer": answer}
                if answer
                else {"role": "assistant", "content": "Conversation closed."}
            )
        except Exception as error:
            state["messages"].append(
                {
                    "role": "assistant",
                    "content": f"Assistant unavailable ({type(error).__name__}). "
                    "Saved records are retained.",
                }
            )
        if adapter and adapter.new_assessment:
            st.session_state.analysis_chat_expanded = False
            select_new_run(adapter.new_assessment)
        st.rerun()
    if state["messages"] and st.button("Clear conversation", key=f"analysis_chat_clear_{scope}"):
        if "conversation" in state:
            state["conversation"].close()
        st.session_state.analysis_chats.pop(assessment.assessment_run_id)
        st.rerun()


def close_chat() -> None:
    st.session_state.analysis_chat_expanded = False


@st.dialog("Credit assistant", width="large", on_dismiss=close_chat)
def expanded_chat(workflow: BorrowerWorkflow, assessment: RiskAssessment, mode: str) -> None:
    render_chat(workflow, assessment, mode, expanded=True)
    if st.button("Back to analysis", on_click=with_web_session(close_chat)):
        st.rerun()


def render_borrower_analysis() -> None:
    if st.session_state.pop("_analysis_hide_chat", False):
        st.session_state.analysis_show_chat = False
        close_chat()
    try:
        workflow = get_workflow()
    except Exception as error:
        st.error(f"Could not open the borrower workspace ({type(error).__name__}).")
        return
    service = workflow.portfolio
    names = {b["borrower_id"]: b["borrower_name"] for b in service.borrowers}
    if not names:
        st.info("No borrowers are registered.")
        return
    if st.button("Back to portfolio", key="analysis_back"):
        navigate("Portfolio")
    pending = st.session_state.pop("_analysis_open_borrower", None)
    if pending:
        st.session_state.analysis_borrower = pending
    if st.session_state.get("analysis_borrower") not in names:
        previous_borrower = st.session_state.get("analysis_saved_selection", {}).get("borrower_id")
        selected_borrower = previous_borrower or st.session_state.get("portfolio_borrower")
        st.session_state.analysis_borrower = (
            selected_borrower if selected_borrower in names else next(iter(names))
        )
    title, switcher, help_column = st.columns([3, 2, 0.8], vertical_alignment="bottom")
    borrower_id = switcher.selectbox(
        "Switch borrower",
        list(names),
        format_func=names.get,
        key="analysis_borrower",
        on_change=with_web_session(select_borrower),
    )
    title.markdown(
        f'<div class="preview-eyebrow">Credit analyst / {escape(borrower_id)}</div>',
        unsafe_allow_html=True,
    )
    title.title(names[borrower_id])

    with help_column.popover("Help", width="stretch"):
        st.markdown(TOPICS["Read an assessment"])
        st.markdown(TOPICS["Ask the assistant"])
        if st.button("Open user guide", key="analysis_open_guide"):
            navigate("User guide")
    period_column, cutoff_col, version_column = st.columns(3)
    st.caption(
        f"{borrower_id} · "
        f"{next(b['industry'] for b in service.borrowers if b['borrower_id'] == borrower_id)} · "
        "Saved calculations and analyst decisions · Synthetic inputs"
    )
    periods = service.periods()
    if not periods:
        st.info("No reporting periods are available in the source catalog.")
        return
    options = [p.isoformat() for p in reversed(periods)]
    remembered = st.session_state.get("analysis_saved_selection", {})
    if remembered.get("borrower_id") != borrower_id:
        remembered = {}
    if st.session_state.get("analysis_period") not in options:
        portfolio_period = st.session_state.get("portfolio_period")
        target = service.target_period(
            borrower_id, None, st.session_state.get("portfolio_cutoff", periods[-1])
        )
        candidate = remembered.get("period") or (
            portfolio_period if portfolio_period in options else str(target)
        )
        st.session_state.analysis_period = candidate if candidate in options else options[0]
    period = date.fromisoformat(
        period_column.selectbox("Reporting period", options, key="analysis_period")
    )
    cutoff = cutoff_col.date_input(
        "Information cutoff",
        value=remembered.get("cutoff", st.session_state.get("portfolio_cutoff", period)),
        key="analysis_cutoff",
    )
    if "analysis_prediction" not in st.session_state:
        st.session_state.analysis_prediction = remembered.get(
            "prediction_mode", DEFAULT_APP_PREDICTION_MODE
        )
    requested_mode = st.session_state.pop("_analysis_next_prediction", None)
    if requested_mode:
        st.session_state.analysis_prediction = requested_mode
    mode = st.session_state.analysis_prediction
    st.session_state.analysis_saved_selection = {
        "borrower_id": borrower_id,
        "period": period.isoformat(),
        "cutoff": cutoff,
        "prediction_mode": mode,
    }
    if cutoff < period:
        st.error("Information cutoff must be on or after the reporting period.")
        return
    entries = service.snapshot(period_end=period, cutoff=cutoff)
    entry = next(e for e in entries if e.borrower_id == borrower_id)
    versions = [
        (a, t)
        for a, t in service.repository.assessment_history(borrower_id)
        if a.period_end == period and a.information_cutoff <= cutoff
    ]
    assessment = entry.assessment
    if versions:
        by_id = {a.assessment_run_id: (a, t) for a, t in versions}
        next_run = st.session_state.pop("_analysis_next_run", None)
        version_context = (borrower_id, period, cutoff)
        if next_run in by_id:
            st.session_state.analysis_version = next_run
        elif (
            st.session_state.get("analysis_version_context") != version_context
            or st.session_state.get("analysis_version") not in by_id
        ):
            st.session_state.analysis_version = assessment.assessment_run_id
        st.session_state.analysis_version_context = version_context
        selected = version_column.selectbox(
            "Assessment version",
            list(by_id),
            key="analysis_version",
            format_func=lambda rid: (
                f"v{len(versions) - list(by_id).index(rid)} · "
                f"{portfolio_page.formatted_time(by_id[rid][1])}"
            ),
        )
        assessment = by_id[selected][0]
        entry = replace(
            entry, assessment=assessment, review=service.repository.latest_review(selected)
        )
    if entry.last_error:
        st.error(entry.last_error)
    if not versions:
        version_column.caption("Saved version: none")
    actions, assistant_column = st.columns([3, 1])
    if "_analysis_next_section" in st.session_state:
        st.session_state.analysis_section = st.session_state.pop("_analysis_next_section")
    with actions, st.container(horizontal=True):
        run = st.button(
            "Run new assessment" if assessment else "Run assessment",
            type="secondary" if assessment else "primary",
            key="analysis_run",
        )
        if assessment:
            st.button(
                "Review and submit",
                type="primary",
                key="analysis_handoff",
                on_click=with_web_session(select_review_section),
            )
        if st.button("Source documents", key="analysis_documents"):
            st.session_state._documents_open_borrower = borrower_id
            navigate("Documents & data")
    show_chat = assistant_column.toggle("Ask assistant", value=False, key="analysis_show_chat")
    if run:
        try:
            with st.status("Calculating and saving assessment…"):
                new = workflow.assess(borrower_id, period, cutoff, prediction_mode=mode)
        except Exception as error:
            st.error(f"Assessment failed ({type(error).__name__}). Saved versions are retained.")
        else:
            select_new_run(new)
    if assessment is None:
        st.info("Not assessed. Run an assessment for these dates. Missing inputs remain explicit.")
        return
    if workflow.needs_review(assessment.assessment_run_id):
        st.warning(
            "Sources changed after this saved assessment. Inspect Documents & data and "
            "reassess before validating or submitting. Earlier reports remain unchanged."
        )
    if assessment.ml_status == "disabled":
        st.info(
            "This saved assessment was created with ML off. "
            "Run it with ML to save a forecast, then rerun the credit review."
        )
        if st.button("Run assessment with ML", key="analysis_enable_ml"):
            try:
                with st.status("Calculating and saving the model forecast…"):
                    new = workflow.enable_ml(assessment.assessment_run_id)
            except Exception as error:
                st.error(f"ML assessment failed ({type(error).__name__}). Saved versions retained.")
            else:
                st.session_state._analysis_next_prediction = DEFAULT_APP_PREDICTION_MODE
                select_new_run(new)
    st.caption(
        f"Saved period {assessment.period_end} · Saved cutoff {assessment.information_cutoff}"
    )
    if cutoff != assessment.information_cutoff:
        st.info(
            "This saved version uses an earlier cutoff. Run assessment to use the selected cutoff."
        )
    version = next(
        (
            len(versions) - i
            for i, (saved, _) in enumerate(versions)
            if saved.assessment_run_id == assessment.assessment_run_id
        ),
        1,
    )
    render_status(workflow, assessment, version=version)
    render_summary_metrics(assessment)
    main, assistant = st.columns([3, 1.15]) if show_chat else (st.container(), None)
    with main:
        overview, calculations, handoff, history = st.tabs(
            ["Overview", "Evidence", "Review and submit", "History"],
            key="analysis_section",
            on_change="rerun",
        )
        with overview:
            st.subheader("The current credit picture")
            if assessment.narrative:
                st.write(assessment.narrative)
            st.caption(
                f"Saved period {assessment.period_end} · Cutoff {assessment.information_cutoff}"
            )
            render_covenant_table(assessment, key="analysis_covenant_overview")
            if entry.review and entry.review.recommendation:
                st.subheader("AI recommendation")
                st.write(entry.review.recommendation.rationale)
                st.caption(
                    f"Advisory · {entry.review.recommendation.action} · "
                    f"Confidence: {entry.review.recommendation.confidence}"
                )
            with st.expander("AI review", expanded=False):
                portfolio_page.render_review_controls(
                    entry, service, bool(os.getenv("OPENAI_API_KEY", "").strip())
                )
            render_saved_trend(assessment)
            with st.expander("Next-quarter forecast", expanded=False):
                render_prediction(assessment)
            st.subheader("Items requiring attention")
            if entry.needs_data:
                st.warning("Data gaps or verification issues need review in Evidence.")
            render_flags(workflow, borrower_id)
        with calculations:
            render_calculation_tables(assessment)
            with st.expander("Recalculate with revised financial inputs"):
                st.caption(
                    "Select metrics to revise. Clear a value to record a missing input. "
                    "Amounts use the source currency and scale shown under Calculations."
                )
                metrics = st.multiselect(
                    "Metrics to revise",
                    FINANCIAL_METRICS,
                    format_func=lambda value: value.replace("_", " ").title(),
                    key=f"analysis_revision_metrics_{assessment.assessment_run_id}",
                )
                saved_periods = SavedFinancials(assessment).get_period_history(
                    borrower_id, as_of=period
                )
                financials = next((p for p in saved_periods if p.period_end == period), None)
                with st.form(f"analysis_recalculate_{assessment.assessment_run_id}"):
                    overrides = {
                        metric: st.number_input(
                            f"Revised {metric.replace('_', ' ')}",
                            value=financials.metrics.get(metric) if financials else None,
                            step=0.1,
                            format="%.4f",
                            key=f"analysis_revision_{assessment.assessment_run_id}_{metric}",
                        )
                        for metric in metrics
                    }
                    reason = st.text_input(
                        "Reason for recalculation",
                        key=f"analysis_reason_{assessment.assessment_run_id}",
                    )
                    if st.form_submit_button("Recalculate"):
                        try:
                            if not overrides:
                                raise ValueError("Supply at least one revised metric.")
                            with st.status("Recalculating and saving a new version…"):
                                new = workflow.assess(
                                    borrower_id,
                                    period,
                                    cutoff,
                                    prediction_mode=mode,
                                    parent_id=assessment.assessment_run_id,
                                    reason=reason,
                                    overrides=overrides,
                                )
                        except ValueError as error:
                            st.warning(str(error))
                        except Exception as error:
                            st.error(
                                f"Recalculation failed ({type(error).__name__}). "
                                "Saved versions retained."
                            )
                        else:
                            select_new_run(new)
        with handoff:
            render_handoff(workflow, assessment)
        with history:
            render_history_table(workflow, versions, assessment.assessment_run_id)
            for saved, created in versions:
                with st.expander(
                    f"{portfolio_page.formatted_time(created)} · {saved.assessment_run_id}"
                ):
                    st.json(saved.model_dump(mode="json"), expanded=False)
                    for event in workflow.repository.events(saved.assessment_run_id):
                        st.write(f"{event['kind']} · {event['created_at']}")
                        st.json(event["payload"], expanded=False)
                    for review in service.repository.review_history(saved.assessment_run_id):
                        st.json(review.model_dump(mode="json"), expanded=False)
            for submission in workflow.repository.submissions(borrower_id):
                with st.expander(
                    f"Submitted {submission['created_at']} · {submission['submission_id']}"
                ):
                    payload = submission["payload"]
                    st.write(payload["text"])
                    st.caption(
                        f"Analyst: {payload.get('analyst') or 'Unspecified'} · "
                        f"Flags: {len(payload.get('flags', []))}"
                    )
                    if payload.get("triage"):
                        st.write(payload["triage"])
                    with st.expander("Raw submission record"):
                        st.json(payload, expanded=False)
    if assistant is not None:
        with assistant, st.container(border=True):
            heading, expand, hide = st.columns([2, 1, 0.8])
            heading.subheader("Credit assistant")
            if expand.button("Expand", key="analysis_chat_expand", width="stretch"):
                st.session_state.analysis_chat_expanded = True
            if hide.button("Hide", key="analysis_chat_hide", width="stretch"):
                st.session_state._analysis_hide_chat = True
                st.rerun()
            if not st.session_state.get("analysis_chat_expanded", False):
                render_chat(workflow, assessment, mode)
    if not show_chat:
        close_chat()
    if st.session_state.get("analysis_chat_expanded", False):
        expanded_chat(workflow, assessment, mode)
