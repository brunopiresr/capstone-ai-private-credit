"""Explicitly labeled, fixed benchmark examples, separate from working assessments."""

# ruff: noqa: E501

import pandas as pd
import streamlit as st

from credit_monitoring.application.demo_assessment_service import build_portfolio_snapshot


def _status_chip(status: str) -> str:
    return f'<span class="status-chip status-{status}">● {status}</span>'


def _fmt(value: float | None, unit: str = "x") -> str:
    return "Unavailable" if value is None else f"{value:.2f}{unit}"


def render_portfolio(
    status_filter: str,
    period_filter: str,
    search_text: str,
) -> None:
    """Render the portfolio cockpit and route a selected row to its assessment."""
    period = None if period_filter == "Latest available" else period_filter
    items = build_portfolio_snapshot(period)
    status_filters = {
        "All borrowers": {"COMPLIANT", "WATCH", "BREACH", "INCOMPLETE"},
        "Needs attention": {"WATCH", "BREACH", "INCOMPLETE"},
        "Watch & breach": {"WATCH", "BREACH"},
        "Breach": {"BREACH"},
        "Watch": {"WATCH"},
        "Incomplete": {"INCOMPLETE"},
        "Compliant": {"COMPLIANT"},
    }
    items = [
        item
        for item in items
        if item.assessment.status in status_filters[status_filter]
        and (
            not search_text
            or search_text.casefold() in item.assessment.borrower_name.casefold()
            or search_text.casefold() in item.assessment.borrower_id.casefold()
            or search_text.casefold() in item.industry.casefold()
        )
    ]
    attention_count = sum(item.assessment.status != "COMPLIANT" for item in items)
    breach_count = sum(item.assessment.status == "BREACH" for item in items)
    incomplete_count = sum(item.assessment.status == "INCOMPLETE" for item in items)

    st.markdown(
        """
        <div class="page-head">
          <div><div class="eyebrow">Portfolio monitoring / Overview</div>
          <h1>Benchmark portfolio (mock)</h1>
          <div class="page-subtitle">Scan the book, spot the exceptions, then open a borrower review.</div></div>
          <div class="demo-pill">MOCK · EXPECTED BENCHMARK ANSWERS</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if period is None:
        st.caption("Showing each borrower's latest available benchmark period.")
    else:
        st.caption(f"Showing benchmark cases for period ending {period}.")

    metric_columns = st.columns(4)
    metric_columns[0].metric("Borrowers in view", len(items))
    metric_columns[1].metric("Need attention", attention_count)
    metric_columns[2].metric("Breach", breach_count)
    metric_columns[3].metric("Incomplete", incomplete_count)

    st.markdown("### Monitoring watchlist")
    st.caption("Rows are prioritized by breach, watch, incomplete data, then compliant status.")
    if not items:
        st.info("No benchmark cases match these filters.")
        return

    table_rows = [
        {
            "Borrower": item.assessment.borrower_name,
            "ID": item.assessment.borrower_id,
            "Industry": item.industry,
            "Period": item.assessment.period_end,
            "Covenant": item.assessment.covenant_id,
            "Result": _fmt(item.assessment.metric, item.assessment.unit),
            "Limit": f"{item.assessment.operator} {item.assessment.threshold:.2f}{item.assessment.unit}",
            "Headroom": _fmt(item.assessment.headroom, item.assessment.unit),
            "Trend": item.trend,
            "Status": item.assessment.status,
            "Next step": item.action,
        }
        for item in items
    ]
    selected_event = st.dataframe(
        pd.DataFrame(table_rows),
        key="portfolio_watchlist",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        use_container_width=True,
    )
    selected_rows = selected_event.selection.rows
    focus_columns = st.columns([1, 3])
    with focus_columns[0]:
        if st.button(
            "Open borrower review →",
            type="primary",
            disabled=not selected_rows,
            use_container_width=True,
        ):
            item = items[selected_rows[0]]
            st.session_state.pending_focus = {
                "borrower_id": item.assessment.borrower_id,
                "borrower_name": item.assessment.borrower_name,
                "period_end": item.assessment.period_end,
            }
            st.rerun()
    with focus_columns[1]:
        st.caption(
            "Select a row, then open its borrower assessment to inspect inputs and evidence."
        )
