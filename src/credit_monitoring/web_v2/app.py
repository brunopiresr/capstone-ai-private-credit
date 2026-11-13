"""Credit Monitor V2: Modern role-based web interface for Credit Analysts & Risk Managers."""

import os

import dotenv
import streamlit as st

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.observability import configure_observability
from credit_monitoring.paths import ROOT
from credit_monitoring.persistence.workflow_repository import WorkflowRepository
from credit_monitoring.web import portfolio as portfolio_page
from credit_monitoring.web.source_watch import watch_application_sources
from credit_monitoring.web.telemetry import with_web_session
from credit_monitoring.web_v2.components.header import render_header
from credit_monitoring.web_v2.style import render_v2_style
from credit_monitoring.web_v2.views.analyst import render_credit_analyst_view
from credit_monitoring.web_v2.views.documents import render_documents_view
from credit_monitoring.web_v2.views.risk_manager import render_risk_manager_view


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


@with_web_session
def main() -> None:
    watch_application_sources()
    st.set_page_config(
        page_title="Credit Monitor · V2",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    dotenv.load_dotenv(ROOT / ".env")
    configure_observability()
    render_v2_style()

    try:
        workflow = get_workflow()
        periods = workflow.portfolio.periods()
    except Exception as err:
        st.error(f"Failed to initialize credit workflow: {type(err).__name__}: {err}")
        return

    # Render top bar & role switcher (defaults to Credit Analyst)
    active_role, selected_period, cutoff = render_header(periods)

    # Route view by role
    if active_role == "👤 Credit Analyst":
        render_credit_analyst_view(workflow, selected_period, cutoff)
    elif active_role == "🛡️ Risk Manager":
        render_risk_manager_view(workflow, selected_period, cutoff)
    elif active_role == "📁 Documents & Data":
        render_documents_view()
    else:
        render_credit_analyst_view(workflow, selected_period, cutoff)

    # Clean footer
    st.divider()
    st.caption(
        "Credit Monitor V2 · Dual-Persona Credit Decision Platform · "
        "AI Assistant & Copilot Enabled · Synthetic Financial Model"
    )


if __name__ == "__main__":
    main()
