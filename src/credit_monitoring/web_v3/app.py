"""Run with make preview-v3. Shared durable data, independent V3 navigation."""

import json
from datetime import date

import dotenv
import streamlit as st

from credit_monitoring.observability import configure_observability
from credit_monitoring.paths import ROOT
from credit_monitoring.web.source_watch import watch_application_sources
from credit_monitoring.web.telemetry import with_web_session
from credit_monitoring.web_v3.services import get_services
from credit_monitoring.web_v3.state import go, remember, restore
from credit_monitoring.web_v3.style import render_style

NAVIGATION = ["Analyst queue", "Risk manager", "Documents", "Board reports", "Settings", "Help"]


@with_web_session
def main() -> None:
    watch_application_sources()
    st.set_page_config(page_title="Credit Monitor · V3", page_icon="◈", layout="wide")
    dotenv.load_dotenv(ROOT / ".env")
    configure_observability()
    restore()
    render_style()
    try:
        services = get_services()
    except Exception as error:
        st.error(f"Could not open the shared workspace ({type(error).__name__}).")
        return
    periods = services.analyst.portfolio.periods()
    st.session_state.setdefault("v3_page", "Analyst queue")
    destination = f"{st.session_state.v3_page}:{st.session_state.get('v3_borrower', '')}"
    st.html(
        "<script>if (window.creditMonitorV3Route !== " + json.dumps(destination) + ") {"
        "window.creditMonitorV3Route = " + json.dumps(destination) + ";"
        "requestAnimationFrame(() => document.querySelector('[data-testid=stMain]')"
        "?.scrollTo(0, 0));}</script>",
        unsafe_allow_javascript=True,
    )
    st.session_state.setdefault("v3_period", "latest")
    st.session_state.setdefault("v3_cutoff", periods[-1] if periods else date.today())
    if "v3_download_identity" in st.session_state:
        services.documents.processor.user_agent = st.session_state.v3_download_identity
    if st.query_params.get("report_id") and st.query_params["report_id"] != st.session_state.get(
        "v3_report_link_seen"
    ):
        st.session_state.v3_page = "Board reports"
    with st.sidebar:
        st.title("◈ Credit Monitor")
        st.caption("V3 · YOUR CREDIT WORK QUEUE")
        page = st.session_state.v3_page
        group = {
            "Borrower": "Analyst queue",
            "Assistant": "Analyst queue",
            "Risk case": "Risk manager",
        }.get(page, page)
        st.session_state.v3_nav = group

        def choose_page():
            if st.session_state.v3_nav == "Documents" and st.session_state.v3_page != "Documents":
                st.session_state.v3_document_return = st.session_state.v3_page
            st.session_state.v3_page = st.session_state.v3_nav

        st.radio("Workspace", NAVIGATION, key="v3_nav", on_change=with_web_session(choose_page))
        st.divider()
        st.selectbox(
            "Reporting period",
            ["latest", *[p.isoformat() for p in reversed(periods)]],
            format_func=lambda p: "Latest per borrower" if p == "latest" else p,
            key="v3_period",
        )
        st.date_input("Information cutoff", key="v3_cutoff")
        st.caption("Shared saved data · Changes are also visible in the existing app.")
        st.caption("Demo · Synthetic financial inputs")
    period = (
        None
        if st.session_state.v3_period == "latest"
        else date.fromisoformat(st.session_state.v3_period)
    )
    cutoff = st.session_state.v3_cutoff
    if period and cutoff < period:
        st.error("Information cutoff must be on or after the reporting period.")
        remember()
        return
    if notice := st.session_state.pop("v3_notice", None):
        st.success(notice)
    from credit_monitoring.web_v3.analyst import render_borrower, render_queue
    from credit_monitoring.web_v3.documents import render_documents
    from credit_monitoring.web_v3.manager import render_case
    from credit_monitoring.web_v3.manager import render_queue as render_risk_queue
    from credit_monitoring.web_v3.reporting import render_board, render_settings

    try:
        page = st.session_state.v3_page
        if page == "Analyst queue":
            render_queue(services, period, cutoff)
        elif page in {"Borrower", "Assistant"}:
            render_borrower(services, period, cutoff, assistant=page == "Assistant")
        elif page == "Documents":
            render_documents(services, period, cutoff)
        elif page == "Risk manager":
            render_risk_queue(services, period or cutoff, cutoff)
        elif page == "Risk case":
            render_case(services, period or cutoff, cutoff)
        elif page == "Board reports":
            render_board(services, period or cutoff, cutoff)
        elif page == "Settings":
            render_settings(services)
        else:
            st.title("How to work in V3")
            st.markdown("""1. Open **Analyst queue** and choose a borrower needing attention.
2. Configure the period's document checklist and explicitly attach linked HTML sources.
3. Process and inspect evidence, then run the covenant assessment. Update financials explicitly.
4. Optionally generate AI credit analysis or ask questions in the wide assistant.
5. Record findings, triage breaches, complete all three checks, validate, and submit.
6. In **Risk manager**, open a case, inspect evidence and responses, and record a decision.
7. Prepare and finalize a report under **Board reports**.

Document checklist gaps warn only. Processed evidence still needs human inspection.
AI requires configured model access. SEC downloads require a download identity in Settings.
HTML is supported; PDF and uploads are deferred. Keep Documents open while processing.
Saved submissions and final board reports are frozen; new work creates later versions.
Chat memory and unsaved drafts last for the browser session; use Save draft for durable findings.
""")
            if st.button("Open analyst queue", key="v3btn_help_queue"):
                go("Analyst queue")
    finally:
        remember()


if __name__ == "__main__":
    main()
