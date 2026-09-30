"""Streamlit analyst workspace with synthetic assessments and a mocked assistant."""

# Inline CSS and compact HTML fragments are intentionally kept with their presentation layer.
# ruff: noqa: E501

from __future__ import annotations

import pandas as pd
import streamlit as st

from credit_monitoring.application.demo_assessment_service import (
    DemoAssessment,
    build_demo_assessment,
    build_portfolio_snapshot,
    get_borrowers,
    get_periods,
    get_portfolio_periods,
)

st.set_page_config(
    page_title="Covenant Monitor | AI Credit Monitoring",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
    :root {
      --ink: #172720; --muted: #66756d; --line: #e4e9e3; --paper: #f7f8f5;
      --green: #214d3a; --green-soft: #e6f0e7; --lime: #c8ef76; --amber: #f5d88d;
      --red: #c9584b; --card: #ffffff;
    }
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; color: var(--ink); }
    .stApp { background: var(--paper); }
    [data-testid="stHeader"] { background: rgba(247,248,245,.94); }
    [data-testid="stSidebar"] { background: #f0f3ed; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
    .block-container { max-width: 1440px; padding: 1.5rem 2.6rem 3rem; }
    h1, h2, h3 { font-family: 'Manrope', sans-serif; letter-spacing: -0.035em; color: var(--ink); }
    h1 { font-size: 2.3rem !important; font-weight: 800 !important; }
    h2 { font-size: 1.35rem !important; font-weight: 750 !important; }
    .brand { display:flex; align-items:center; gap:.7rem; margin:.35rem 0 1.8rem; }
    .brand-mark { width:2.35rem; height:2.35rem; display:grid; place-items:center; border-radius:.75rem; background:var(--green); color:var(--lime); font-size:1.25rem; font-weight:700; }
    .brand-name { font: 800 1rem 'Manrope',sans-serif; line-height:1.1; }
    .brand-caption { color:var(--muted); font-size:.7rem; margin-top:.15rem; }
    .eyebrow { color:var(--green); text-transform:uppercase; letter-spacing:.12em; font-size:.7rem; font-weight:700; }
    .page-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding-bottom:1.1rem; border-bottom:1px solid var(--line); margin-bottom:1.45rem; }
    .page-subtitle { color:var(--muted); margin-top:-.6rem; font-size:.97rem; }
    .demo-pill { border:1px solid #d8e5d6; background:#eef5e9; border-radius:99px; color:var(--green); padding:.45rem .75rem; font-size:.73rem; font-weight:700; white-space:nowrap; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:1rem; padding:1.15rem 1.25rem; box-shadow:0 2px 12px rgba(26,48,35,.025); }
    .panel-label { color:var(--muted); font-size:.76rem; font-weight:600; }
    .metric-value { font:800 1.7rem 'Manrope',sans-serif; letter-spacing:-.04em; margin-top:.4rem; }
    .metric-help { color:var(--muted); font-size:.76rem; margin-top:.25rem; }
    .status-chip { display:inline-flex; align-items:center; gap:.4rem; border-radius:99px; padding:.38rem .7rem; font-size:.72rem; line-height:1; font-weight:800; letter-spacing:.02em; }
    .status-COMPLIANT { background:var(--green-soft); color:var(--green); }
    .status-WATCH { background:#fff2d3; color:#8d5a00; }
    .status-BREACH { background:#fbe8e5; color:#a63e34; }
    .status-INCOMPLETE { background:#ecefed; color:#53615a; }
    .kicker { font-size:.74rem; color:var(--muted); }
    .source-tag { display:inline-block; background:#f0f3ee; border:1px solid var(--line); color:#42544a; border-radius:.4rem; padding:.22rem .46rem; font:600 .68rem ui-monospace,monospace; }
    .chat-note { border-left:3px solid var(--lime); background:#f2f7ea; padding:.8rem 1rem; border-radius:0 .6rem .6rem 0; color:#405447; font-size:.86rem; }
    div.stButton > button[kind="primary"] { background:var(--green); border:0; border-radius:.6rem; color:white; font-weight:700; padding:.65rem 1rem; }
    div.stButton > button[kind="primary"]:hover { background:#173b2b; border:0; color:white; }
    [data-testid="stMetric"] { background:var(--card); border:1px solid var(--line); border-radius:.9rem; padding:1rem 1.05rem; }
    [data-testid="stMetricLabel"] { color:var(--muted); }
    [data-testid="stMetricValue"] { font-family:'Manrope',sans-serif; font-weight:800; letter-spacing:-.04em; }
    div[data-testid="stTabs"] button { font-weight:700; }
    [data-testid="stExpander"] { border-color:var(--line); border-radius:.8rem; }
    @media (max-width: 760px) { .block-container { padding:1rem 1rem 2rem; } .page-head { flex-direction:column; } }
    </style>
    """,
    unsafe_allow_html=True,
)


def _status_chip(status: str) -> str:
    return f'<span class="status-chip status-{status}">● {status}</span>'


def _fmt(value: float | None, unit: str = "x") -> str:
    return "Unavailable" if value is None else f"{value:.2f}{unit}"


def _mock_reply(question: str, assessment: DemoAssessment) -> str:
    """Return a clearly labeled canned reply scoped to the selected demo case."""
    prompt = question.lower()
    value = _fmt(assessment.metric, assessment.unit)
    headroom = _fmt(assessment.headroom, assessment.unit)
    if any(word in prompt for word in ("why", "status", "watch", "risk", "headroom")):
        return (
            f"For **{assessment.borrower_name}** at **{assessment.period_end}**, the benchmark status is "
            f"**{assessment.status}**. The recorded result is **{value}** against a threshold of "
            f"**{assessment.operator} {assessment.threshold:.2f}{assessment.unit}**, with headroom of "
            f"**{headroom}**. {assessment.rationale or 'The benchmark does not include a written rationale.'} "
            f"This canned response uses case `{assessment.case_id}`."
        )
    if any(word in prompt for word in ("source", "evidence", "clause", "document", "cite")):
        issue = (
            f" The benchmark also flags `{assessment.evidence_issue}` for analyst review."
            if assessment.evidence_issue
            else " No evidence issue is flagged in this benchmark case."
        )
        return (
            f"The displayed benchmark references are the synthetic covenant terms and synthetic quarterly "
            f"financials for `{assessment.borrower_id}`. Case ID: `{assessment.case_id}`.{issue} "
            "No live document retrieval is connected in this demo."
        )
    if any(word in prompt for word in ("prior", "trend", "quarter", "change")):
        points = assessment.history
        if len(points) < 2:
            return "This borrower has fewer than two benchmark periods for a trend comparison."
        earlier_date, earlier_value = points[-2]
        later_date, later_value = points[-1]
        direction = "increased" if later_value > earlier_value else "decreased"
        return (
            f"The benchmark metric {direction} from **{earlier_value:.2f}{assessment.unit}** on "
            f"{earlier_date} to **{later_value:.2f}{assessment.unit}** on {later_date}. "
            f"The assessment case is `{assessment.case_id}`."
        )
    return (
        f"I can summarize the selected demo case for **{assessment.borrower_name}**. Its status is "
        f"**{assessment.status}** at **{value}** versus **{assessment.threshold:.2f}{assessment.unit}**. "
        "Try asking about the status, evidence, headroom, or trend."
    )


def _render_portfolio(
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
          <h1>Portfolio cockpit</h1>
          <div class="page-subtitle">Scan the book, spot the exceptions, then open a borrower review.</div></div>
          <div class="demo-pill">DEMO MODE · SYNTHETIC PORTFOLIO</div>
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
        st.caption("Select a row, then open its borrower assessment to inspect inputs and evidence.")


borrowers = get_borrowers()
pending_focus = st.session_state.pop("pending_focus", None)
if pending_focus:
    st.session_state.workspace_page = "Borrower assessment"
    st.session_state.borrower_select = pending_focus["borrower_name"]
    st.session_state.period_select = pending_focus["period_end"]
    st.session_state.active_case = (
        pending_focus["borrower_id"],
        pending_focus["period_end"],
    )
    st.session_state.chat_messages = []

borrower_labels = {row["borrower_name"]: row["borrower_id"] for row in borrowers}
with st.sidebar:
    st.markdown(
        '<div class="brand"><div class="brand-mark">◈</div><div><div class="brand-name">Credit Monitor</div><div class="brand-caption">Analyst workspace</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="eyebrow">Workspace</div>', unsafe_allow_html=True)
    workspace_page = st.radio(
        "Navigate",
        ["Portfolio cockpit", "Borrower assessment"],
        key="workspace_page",
        label_visibility="collapsed",
    )
    st.divider()
    if workspace_page == "Portfolio cockpit":
        st.markdown("**Portfolio filters**")
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
            key="portfolio_status_filter",
        )
        period_filter = st.selectbox(
            "Reporting period",
            ["Latest available", *get_portfolio_periods()],
            key="portfolio_period_filter",
        )
        portfolio_search = st.text_input("Find borrower or industry", key="portfolio_search")
        selected_name = None
        selected_id = None
        selected_period = None
        run_clicked = False
    else:
        st.markdown('<div class="eyebrow">Quarterly review</div>', unsafe_allow_html=True)
        selected_name = st.selectbox("Borrower", list(borrower_labels), key="borrower_select")
        selected_id = borrower_labels[selected_name]
        periods = get_periods(selected_id)
        selected_period = st.selectbox(
            "Reporting period", periods, index=len(periods) - 1, key="period_select"
        )
        run_clicked = st.button("Run demo assessment", type="primary", use_container_width=True)
        st.divider()
        st.markdown("**Demo workspace**")
        st.caption(f"{len(borrowers)} synthetic borrowers · benchmark data only")
        st.markdown('<div class="chat-note">Agent responses are mocked. No model, live retrieval, or credit decision is involved.</div>', unsafe_allow_html=True)

if workspace_page == "Portfolio cockpit":
    _render_portfolio(status_filter, period_filter, portfolio_search)
    st.divider()
    st.caption("AI Credit Monitoring POC · Synthetic benchmark data · Analyst remains responsible for interpretation and decisions")
    st.stop()

if run_clicked or "active_case" not in st.session_state:
    if run_clicked and st.session_state.get("active_case") != (selected_id, selected_period):
        st.session_state.chat_messages = []
    st.session_state.active_case = (selected_id, selected_period)

active_id, active_period = st.session_state.active_case
if (active_id, active_period) != (selected_id, selected_period):
    st.info("Inputs changed. Select **Run demo assessment** to load this borrower and period.")
assessment = build_demo_assessment(active_id, active_period)

st.markdown(
    """
    <div class="page-head">
      <div><div class="eyebrow">Portfolio monitoring / Assessment</div>
      <h1>Quarterly covenant review</h1>
      <div class="page-subtitle">A traceable view of covenant performance, headroom, and trend.</div></div>
      <div class="demo-pill">DEMO MODE · MOCKED AGENT</div>
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns([2.5, 1], vertical_alignment="center")
with left:
    st.markdown(f"## {assessment.borrower_name}")
    st.markdown(
        f'<span class="kicker">{assessment.borrower_id} &nbsp;·&nbsp; {assessment.scenario.replace("_", " ").title()} &nbsp;·&nbsp; Period ending {assessment.period_end}</span>',
        unsafe_allow_html=True,
    )
with right:
    st.markdown(_status_chip(assessment.status), unsafe_allow_html=True)

if assessment.early_warning:
    st.warning("Early warning benchmark: this case is marked WATCH for deteriorating covenant headroom.")
if assessment.status == "INCOMPLETE":
    st.info("This scenario is waived, not tested, or missing/conflicting inputs. No compliance conclusion is shown.")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Covenant metric", _fmt(assessment.metric, assessment.unit), assessment.covenant_name)
with m2:
    st.metric("Threshold", f"{assessment.operator} {assessment.threshold:.2f}{assessment.unit}", assessment.covenant_id)
with m3:
    st.metric("Headroom", _fmt(assessment.headroom, assessment.unit), "Benchmark value")
with m4:
    if len(assessment.history) > 1:
        change = assessment.history[-1][1] - assessment.history[-2][1]
        st.metric("Quarterly change", f"{change:+.2f}{assessment.unit}", "vs prior benchmark period")
    else:
        st.metric("Quarterly change", "—", "No prior benchmark period")

assessment_tab, evidence_tab, assistant_tab = st.tabs(["Assessment", "Evidence & inputs", "Analyst assistant"])
with assessment_tab:
    trend_col, summary_col = st.columns([1.5, 1])
    with trend_col:
        st.markdown("### Covenant trend")
        st.caption("Benchmark outputs by reporting period. These are static expected results.")
        if assessment.history:
            chart = pd.DataFrame(
                {"Period": [date for date, _ in assessment.history], "Metric (x)": [value for _, value in assessment.history]}
            ).set_index("Period")
            st.line_chart(chart, color="#214d3a", height=235)
        else:
            st.info("No historical benchmark points are available for this case.")
    with summary_col:
        st.markdown("### Analyst summary")
        st.markdown(f'<div class="panel"><div class="panel-label">Scenario note</div><p>{assessment.rationale or "No narrative rationale is included in this benchmark case."}</p><div class="panel-label">Review state</div><p>{_status_chip(assessment.status)}</p><span class="source-tag">{assessment.case_id}</span></div>', unsafe_allow_html=True)
        st.caption("This panel displays benchmark labels and explanatory notes, not a generated credit opinion.")
    st.markdown("### Context signals")
    sig_a, sig_b, sig_c = st.columns(3)
    with sig_a:
        st.markdown('<div class="panel"><div class="panel-label">Legal terms</div><strong>Benchmark covenant record</strong><p class="kicker">Effective term selected from the synthetic covenant table.</p></div>', unsafe_allow_html=True)
    with sig_b:
        st.markdown('<div class="panel"><div class="panel-label">Financials</div><strong>Quarterly benchmark inputs</strong><p class="kicker">Values shown in Evidence & inputs.</p></div>', unsafe_allow_html=True)
    with sig_c:
        st.markdown('<div class="panel"><div class="panel-label">Public context</div><strong>Not connected in demo</strong><p class="kicker">No live public-event retrieval is performed.</p></div>', unsafe_allow_html=True)

with evidence_tab:
    st.markdown("### Covenant and evidence provenance")
    st.caption("Synthetic benchmark records are shown as the supporting material for this demo; no live agreement clauses are retrieved.")
    st.markdown(
        f"**{assessment.covenant_name}** · tested {assessment.period_end} · `{assessment.operator} {assessment.threshold:.2f}{assessment.unit}`  \n"
        f"Formula reference: `{assessment.formula}`"
    )
    st.markdown('<span class="source-tag">synthetic_covenant_terms.csv</span> &nbsp; <span class="source-tag">synthetic_gold_labels.csv</span>', unsafe_allow_html=True)
    st.markdown("### Financial inputs")
    if assessment.financial_facts:
        st.dataframe(
            pd.DataFrame([{"Metric": key.replace("_", " ").title(), "Value": value} for key, value in assessment.financial_facts.items()]),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No financial input values are available for this case.")
    st.markdown("### Benchmark check")
    st.markdown(
        f"- Expected status: **{assessment.status}**  \n"
        f"- Expected metric: **{_fmt(assessment.metric, assessment.unit)}**  \n"
        f"- Expected headroom: **{_fmt(assessment.headroom, assessment.unit)}**  \n"
        f"- Case ID: `{assessment.case_id}`"
    )
    if assessment.evidence_issue:
        st.warning(f"Benchmark evidence issue: `{assessment.evidence_issue}`")

with assistant_tab:
    st.markdown("### Ask about this assessment")
    st.markdown('<div class="chat-note">Mock assistant · Replies use only the selected synthetic case and fixed response templates.</div>', unsafe_allow_html=True)
    st.caption("Try: “Why is this borrower in WATCH?”, “Show the evidence”, or “How did the trend change?”")
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    question = st.chat_input("Ask about status, evidence, headroom, or trend")
    if question:
        st.session_state.chat_messages.append({"role": "user", "content": question})
        answer = _mock_reply(question, assessment)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})
        st.rerun()
    if st.session_state.chat_messages and st.button("Clear conversation"):
        st.session_state.chat_messages = []
        st.rerun()

st.divider()
st.caption("AI Credit Monitoring POC · Synthetic benchmark data · Analyst remains responsible for interpretation and decisions")
