"""Connected Streamlit POC: analyst, documents, risk manager and board workflows."""

import streamlit as st

from credit_monitoring.web.preview_style import render_preview_style
from credit_monitoring.web.source_watch import watch_application_sources
from credit_monitoring.web.user_guide import remember_navigation, render_user_guide

PAGES = [
    "Portfolio",
    "Borrower analysis",
    "Documents & data",
    "Risk review",
    "Board report",
    "User guide",
]


def reset_navigation() -> None:
    for key in list(st.session_state):
        if key.startswith(("preview_", "_preview_")):
            del st.session_state[key]


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="preview-brand"><div class="preview-mark">◈</div>'
            "<div><b>Credit Monitor</b><small>PRIVATE CREDIT WORKSPACE</small></div></div>",
            unsafe_allow_html=True,
        )
        st.caption("NAVIGATION")
        st.radio(
            "Navigation",
            PAGES,
            key="preview_page",
            label_visibility="collapsed",
            on_change=remember_navigation,
        )
        st.divider()
        st.caption("CONNECTED WORKSPACE")
        st.caption("Choose reporting dates on the page. Runs and decisions are saved locally.")
        st.button(
            "Reset navigation", key="preview_reset", on_click=reset_navigation, width="stretch"
        )
        st.caption("Resetting navigation keeps saved assessments, flags, requests and reports.")


def main() -> None:
    watch_application_sources()
    st.set_page_config(
        page_title="Credit Monitor · POC",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    if "_preview_next_page" in st.session_state:
        st.session_state.preview_page = st.session_state.pop("_preview_next_page")
    report_id = st.query_params.get("report_id")
    if report_id and report_id != st.session_state.get("_board_link_seen"):
        st.session_state._board_link_seen = report_id
        st.session_state._board_open_report = report_id
        st.session_state.preview_page = "Board report"
    render_preview_style()
    remember_navigation()
    render_sidebar()
    if st.session_state.preview_page == "User guide":
        render_user_guide()
        return
    if st.session_state.preview_page != "Borrower analysis":
        st.session_state.analysis_chat_expanded = False
    st.markdown(
        '<div class="preview-ribbon"><span><b>CONNECTED WORKSPACE</b> &nbsp; '
        "Saved calculations, credit reviews and decisions</span>"
        "<span>Synthetic financial inputs &nbsp; / &nbsp; Saved locally</span></div>",
        unsafe_allow_html=True,
    )
    from credit_monitoring.web.board_report import render_board_report_page
    from credit_monitoring.web.borrower_analysis import render_borrower_analysis
    from credit_monitoring.web.documents import render_documents_page
    from credit_monitoring.web.portfolio import render_portfolio_page
    from credit_monitoring.web.risk_review import render_risk_review_page

    {
        "Portfolio": render_portfolio_page,
        "Borrower analysis": render_borrower_analysis,
        "Documents & data": render_documents_page,
        "Risk review": render_risk_review_page,
        "Board report": render_board_report_page,
    }[st.session_state.preview_page]()


if __name__ == "__main__":
    main()
