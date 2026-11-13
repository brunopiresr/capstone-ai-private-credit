"""Connected Streamlit POC: analyst, documents, risk manager and board workflows."""

import json

import dotenv
import streamlit as st

from credit_monitoring.observability import configure_observability
from credit_monitoring.paths import ROOT
from credit_monitoring.web.navigation import (
    context,
    navigate,
    remember_workspace,
    restore_workspace,
)
from credit_monitoring.web.preview_style import render_preview_style
from credit_monitoring.web.source_watch import watch_application_sources
from credit_monitoring.web.telemetry import with_web_session
from credit_monitoring.web.user_guide import remember_navigation, render_user_guide

PAGES = ["Portfolio", "Risk review", "Board report", "Documents & data"]
PAGE_LABELS = {"Board report": "Board reports", "Documents & data": "Documents"}


def reset_navigation() -> None:
    st.session_state.pop("workspace_context", None)
    for key in list(st.session_state):
        if key.startswith(("preview_", "_preview_")):
            del st.session_state[key]


def choose_navigation() -> None:
    current = st.session_state.get("preview_page", "Portfolio")
    if st.session_state.preview_navigation == "Documents & data" and current not in {
        "User guide",
        "Settings",
        "Documents & data",
    }:
        context().return_page = current
    st.session_state._preview_next_page = st.session_state.preview_navigation


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="preview-brand"><div class="preview-mark">◈</div>'
            "<div><b>Credit Monitor</b><small>PRIVATE CREDIT WORKSPACE</small></div></div>",
            unsafe_allow_html=True,
        )
        current = st.session_state.get("preview_page", "Portfolio")
        st.session_state.preview_navigation = current if current in PAGES else None
        st.radio(
            "Navigation",
            PAGES,
            index=None,
            key="preview_navigation",
            format_func=lambda page: PAGE_LABELS.get(page, page),
            label_visibility="collapsed",
            on_change=with_web_session(choose_navigation),
        )
        st.divider()
        if st.button("Help", key="workspace_help", width="stretch"):
            navigate("User guide")
        if st.button("Settings", key="workspace_settings", width="stretch"):
            navigate("Settings")
        st.caption("Demo · Synthetic financial inputs")


def render_settings() -> None:
    from credit_monitoring.application.borrower_workflow import PREDICTION_MODES
    from credit_monitoring.config.settings import DEFAULT_APP_PREDICTION_MODE
    from credit_monitoring.web.documents import get_document_workspace, render_maintenance

    if st.button("Back to workspace"):
        navigate(context().return_page)
    st.title("Settings")
    st.selectbox(
        "Prediction mode",
        PREDICTION_MODES,
        index=PREDICTION_MODES.index(DEFAULT_APP_PREDICTION_MODE),
        key="analysis_prediction",
        help="Applies to new assessments. Saved versions keep their original forecast.",
    )
    st.caption(
        "AI reviews and assistant replies require operator-configured OPENAI_API_KEY. "
        "SEC downloads require SEC_USER_AGENT. Saved results remain readable."
    )
    with st.expander("Working data maintenance"):
        try:
            render_maintenance(get_document_workspace())
        except Exception as error:
            st.error(f"Could not open maintenance ({type(error).__name__}).")
    with st.expander("Navigation"):
        st.button(
            "Reset navigation", key="preview_reset", on_click=with_web_session(reset_navigation)
        )
        st.caption("Saved assessments, flags, requests and reports are retained.")


@with_web_session
def main() -> None:
    watch_application_sources()
    st.set_page_config(
        page_title="Credit Monitor · POC",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="auto",
    )
    dotenv.load_dotenv(ROOT / ".env")
    configure_observability()
    restore_workspace()
    st.session_state.setdefault("preview_page", "Portfolio")
    if "_preview_next_page" in st.session_state:
        st.session_state.preview_page = st.session_state.pop("_preview_next_page")
    report_id = st.query_params.get("report_id")
    if report_id and report_id != st.session_state.get("_board_link_seen"):
        st.session_state._board_link_seen = report_id
        st.session_state._board_open_report = report_id
        st.session_state.preview_page = "Board report"
    render_preview_style()
    # Keep this element in the same place on every rerun so widget identities
    # remain stable. Reset scrolling only when the destination changes.
    page_json = json.dumps(st.session_state.preview_page)
    st.html(
        "<script>if (window.creditMonitorPage !== " + page_json + ") {"
        "window.creditMonitorPage = " + page_json + "; requestAnimationFrame(() => {"
        "document.querySelector('[data-testid=stMain]')?.scrollTo(0, 0);"
        "});}</script>",
        unsafe_allow_javascript=True,
    )
    remember_navigation()
    render_sidebar()
    if st.session_state.preview_page != "Borrower analysis":
        st.session_state.analysis_chat_expanded = False
    from credit_monitoring.web.board_report import render_board_report_page
    from credit_monitoring.web.borrower_analysis import render_borrower_analysis
    from credit_monitoring.web.documents import render_documents_page
    from credit_monitoring.web.portfolio import render_portfolio_page
    from credit_monitoring.web.risk_review import render_risk_review_page

    try:
        {
            "Portfolio": render_portfolio_page,
            "Borrower analysis": render_borrower_analysis,
            "Documents & data": render_documents_page,
            "Risk review": render_risk_review_page,
            "Board report": render_board_report_page,
            "User guide": render_user_guide,
            "Settings": render_settings,
        }[st.session_state.preview_page]()
    finally:
        remember_workspace()


if __name__ == "__main__":
    main()
