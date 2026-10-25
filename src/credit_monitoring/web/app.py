"""Working synthetic borrower assessments with a separate benchmark example."""

import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv

from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.observability import configure_observability
from credit_monitoring.web.assessment import (
    render_answer,
    render_evidence,
    render_prediction,
    render_results,
    render_verification,
)
from credit_monitoring.web.style import render_style
from credit_monitoring.web.workspace import (
    DEFAULT_DATA_ROOT,
    DEFAULT_WORKSPACE_DIR,
    PREDICTION_MODES,
    SyntheticWorkspace,
    ask_about_assessment,
    create_conversation,
)


@st.cache_resource(show_spinner=False)
def get_workspace(data_root: str, working_dir: str) -> SyntheticWorkspace:
    """Import bundled inputs once per app startup, independently of browser sessions."""
    from pathlib import Path

    return SyntheticWorkspace(Path(data_root), Path(working_dir))


def clear_conversation() -> None:
    conversation = st.session_state.pop("conversation", None)
    if conversation is not None:
        conversation.close()
    st.session_state.chat_messages = []


def render_assistant(assessment: RiskAssessment, *, pending: bool) -> None:
    st.subheader("Ask about this assessment")
    st.caption(
        "The assistant reads financials and runs calculation/prediction tools for this borrower. "
        "Selected dates are supplied with each question. Change the controls to review other dates."
    )
    credentials_available = bool(os.getenv("OPENAI_API_KEY", "").strip())
    if not credentials_available:
        st.info("Set OPENAI_API_KEY in the environment or .env to enable the analyst assistant.")
    if pending:
        st.info("Run the selected assessment successfully before asking a follow-up.")
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            if "answer" in message:
                render_answer(message["answer"])
            elif "error" in message:
                st.error(message["error"])
            else:
                st.markdown(message["content"])
    question = st.chat_input(
        "Ask about compliance, inputs, evidence, or forecasts",
        disabled=pending or not credentials_available,
    )
    if question:
        st.session_state.chat_messages.append({"role": "user", "content": question})
        try:
            conversation = st.session_state.get("conversation")
            if conversation is None or conversation.closed:
                conversation = create_conversation(
                    st.session_state.assessment_service, assessment.borrower_id
                )
                st.session_state.conversation = conversation
            with st.spinner("Reading assessment evidence…"):
                answer = ask_about_assessment(conversation, question, assessment)
            message = {"role": "assistant"}
            if answer is None:
                message["content"] = (
                    "Conversation closed. Your next question starts a new conversation."
                )
            else:
                message["answer"] = answer
            st.session_state.chat_messages.append(message)
        except Exception as error:
            st.session_state.chat_messages.append(
                {
                    "role": "assistant",
                    "error": f"Assistant unavailable: {type(error).__name__}: {error}",
                }
            )
        st.rerun()
    if st.session_state.chat_messages and st.button("Clear conversation"):
        clear_conversation()
        st.rerun()


st.set_page_config(page_title="Covenant Monitor", page_icon="◈", layout="wide")
load_dotenv(DEFAULT_DATA_ROOT.parent / ".env")
configure_observability()
render_style()

pending_focus = st.session_state.pop("pending_focus", None)
if pending_focus:
    st.session_state.workspace_page = "Borrower assessment"
    st.session_state.borrower_select = pending_focus["borrower_id"]
    st.session_state.period_select = pending_focus["period_end"]

with st.sidebar:
    st.title("◈ Credit Monitor")
    page = st.radio(
        "Workspace", ["Borrower assessment", "Benchmark portfolio (mock)"], key="workspace_page"
    )

if page == "Benchmark portfolio (mock)":
    from credit_monitoring.application.demo_assessment_service import get_portfolio_periods
    from credit_monitoring.web.benchmark import render_portfolio

    with st.sidebar:
        status_filter = st.selectbox(
            "Attention view",
            [
                "Needs attention",
                "All borrowers",
                "Watch & breach",
                "Breach",
                "Watch",
                "Incomplete",
                "Compliant",
            ],
        )
        period_filter = st.selectbox(
            "Reporting period", ["Latest available", *get_portfolio_periods()]
        )
        search = st.text_input("Find borrower or industry")
    st.info(
        "Fixed benchmark examples. These expected answers are separate from "
        "working service results."
    )
    render_portfolio(status_filter, period_filter, search)
    st.stop()

st.title("Quarterly covenant review")
st.caption("Working services · Synthetic inputs · Analyst review required")
try:
    workspace = get_workspace(str(DEFAULT_DATA_ROOT), str(DEFAULT_WORKSPACE_DIR))
except Exception as error:
    st.error(f"Could not prepare the synthetic workspace: {type(error).__name__}: {error}")
    st.stop()
if not workspace.borrowers:
    st.info("No borrowers with financial inputs are available.")
    st.stop()
names = {row["borrower_id"]: row["borrower_name"] for row in workspace.borrowers}
with st.sidebar:
    st.subheader("Quarterly review")
    borrower_id = st.selectbox(
        "Borrower",
        list(names),
        format_func=lambda value: f"{names[value]} ({value})",
        key="borrower_select",
    )
    periods = workspace.periods(borrower_id)
    if st.session_state.get("period_select") not in periods:
        st.session_state.period_select = periods[-1]
    selected_period = st.selectbox("Reporting period", periods, key="period_select")
    period = date.fromisoformat(selected_period)
    if st.session_state.get("cutoff_context") != (borrower_id, selected_period):
        st.session_state.information_cutoff = period
        st.session_state.cutoff_context = (borrower_id, selected_period)
    cutoff = st.date_input("Information cutoff", key="information_cutoff")
    prediction_mode = st.selectbox("Prediction mode", PREDICTION_MODES, key="prediction_mode")
    if prediction_mode == "Logistic Regression":
        st.caption("Requires the optional ml dependencies and saved synthetic model artifact.")
    invalid_cutoff = cutoff < period
    if invalid_cutoff:
        st.error("Information cutoff must be on or after the reporting period.")
    run_clicked = st.button("Run assessment", type="primary", disabled=invalid_cutoff)
    st.caption("Inputs are imported into dedicated app storage once per startup.")

selection = (borrower_id, selected_period, cutoff.isoformat(), prediction_mode)
if run_clicked:
    clear_conversation()
    try:
        with st.spinner("Calculating and verifying covenants…"):
            service = workspace.assessment_service(prediction_mode)
            assessment = service.assess(borrower_id, period, cutoff)
        st.session_state.active_assessment = assessment
        st.session_state.active_selection = selection
        st.session_state.assessment_service = service
        st.session_state.pop("assessment_error", None)
    except Exception as error:
        st.session_state.assessment_error = f"Assessment failed: {type(error).__name__}: {error}"

if st.session_state.get("assessment_error"):
    st.error(st.session_state.assessment_error)
if "active_assessment" not in st.session_state:
    st.info("Select a borrower and reporting dates, then run the assessment.")
    st.stop()
assessment = st.session_state.active_assessment
pending = selection != st.session_state.active_selection or bool(
    st.session_state.get("assessment_error")
)
if pending:
    st.info(
        "Inputs changed or the latest run failed. The previous assessment remains below; "
        "run the selected assessment to update it."
    )
st.header(names[assessment.borrower_id])
assessment_tab, evidence_tab, assistant_tab = st.tabs(
    ["Assessment", "Evidence & inputs", "Analyst assistant"]
)
with assessment_tab:
    render_results(assessment)
    render_verification(assessment)
    render_prediction(assessment)
with evidence_tab:
    render_evidence(assessment)
with assistant_tab:
    render_assistant(assessment, pending=pending)
st.divider()
st.caption(
    "AI Credit Monitoring POC · Synthetic inputs · "
    "Analyst remains responsible for interpretation and decisions"
)
