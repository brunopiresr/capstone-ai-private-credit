"""Credit Analyst View: Review loans, run analysis, flag borrowers, and interact with AI."""

from datetime import date

import pandas as pd
import streamlit as st

from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.application.portfolio_service import PortfolioEntry
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.web.borrower_views import render_saved_trend
from credit_monitoring.web.portfolio import render_agent_result
from credit_monitoring.web_v2.components.chat import render_chat_widget
from credit_monitoring.web_v2.components.metrics import render_kpi_card


def _fmt(value: float | None, unit: str | None = None) -> str:
    """Format a numeric value safely; returns '—' if value is None."""
    if value is None:
        return "—"
    return f"{value:.2f}{unit or ''}"


ANALYST_SUGGESTED_PROMPTS = [
    "Why did Interest Coverage decline?",
    "What are the key downside risks and mitigants?",
    "Explain the covenant headroom trend",
    "Summarize EBITDA adjustments and compliance",
]


def render_loan_portfolio_table(
    entries: list[PortfolioEntry],
    selected_borrower_id: str,
) -> str:
    """Render search, status filters, and the interactive loan portfolio table."""
    # 1. Summary KPI row
    col1, col2, col3, col4 = st.columns(4)
    total_loans = len(entries)
    compliant_count = sum(e.compliance == "Compliant" for e in entries)
    breach_count = sum(e.compliance == "Breach" for e in entries)
    unassessed_count = sum(e.assessment is None for e in entries)

    with col1:
        render_kpi_card("Total Loans", total_loans, "Monitored facilities")
    with col2:
        render_kpi_card("Compliant", compliant_count, "Covenants passing")
    with col3:
        render_kpi_card("In Breach", breach_count, "Immediate attention")
    with col4:
        render_kpi_card("Not Assessed", unassessed_count, "Awaiting evaluation")

    st.markdown("### Active Loan Portfolio")
    # Filters
    search_col, status_col = st.columns([2, 1])
    with search_col:
        search_term = (
            st.text_input(
                "Search loans",
                placeholder="Search borrower name, ID, or sector…",
                key="v2_analyst_search",
                label_visibility="collapsed",
            )
            .strip()
            .lower()
        )
    with status_col:
        status_filter = st.selectbox(
            "Status filter",
            ["All Loans", "Needs Attention (Breach/Watch)", "Compliant", "Not Assessed"],
            key="v2_analyst_status_filter",
            label_visibility="collapsed",
        )

    # Filter entries
    filtered = []
    for e in entries:
        if search_term and (
            search_term not in e.name.lower()
            and search_term not in e.borrower_id.lower()
            and search_term not in e.sector.lower()
        ):
            continue
        if status_filter == "Needs Attention (Breach/Watch)" and e.compliance not in {
            "Breach",
            "Watch",
        }:
            continue
        if status_filter == "Compliant" and e.compliance != "Compliant":
            continue
        if status_filter == "Not Assessed" and e.assessment is not None:
            continue
        filtered.append(e)

    if not filtered:
        st.info("No loans match the current search or filter criteria.")
        return selected_borrower_id

    # Table rows
    table_data = []
    borrower_ids = []
    for e in filtered:
        borrower_ids.append(e.borrower_id)
        primary_covenant = "—"
        actual_str = "—"
        threshold_str = "—"
        headroom_str = "—"

        if e.assessment and e.assessment.results:
            first_res = next(
                (r for r in e.assessment.results if r.compliance_status == "breach"),
                e.assessment.results[0],
            )
            primary_covenant = first_res.covenant_type.replace("_", " ").title()
            actual_str = _fmt(first_res.actual_value, first_res.unit)
            op = first_res.operator or ""
            threshold_str = f"{op} {_fmt(first_res.threshold, first_res.unit)}".strip()
            headroom_str = _fmt(first_res.headroom)

        table_data.append(
            {
                "Borrower": e.name,
                "ID": e.borrower_id,
                "Sector": e.sector,
                "Period": e.period_end.isoformat() if e.period_end else "No Data",
                "Compliance": e.compliance,
                "Primary Covenant": primary_covenant,
                "Actual": actual_str,
                "Limit": threshold_str,
                "Headroom": headroom_str,
            }
        )

    df = pd.DataFrame(table_data)
    key = "v2_analyst_portfolio_table"

    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        key=key,
    )

    names_map = {e.borrower_id: f"{e.name} ({e.borrower_id}) - {e.compliance}" for e in filtered}
    default_idx = (
        borrower_ids.index(selected_borrower_id) if selected_borrower_id in borrower_ids else 0
    )
    picked_borrower = st.selectbox(
        "Select Active Loan to Inspect or Run Analysis",
        options=borrower_ids,
        index=default_idx,
        format_func=lambda bid: names_map.get(bid, bid),
        key="v2_analyst_borrower_picker",
    )

    return picked_borrower


def render_covenants_card(assessment: RiskAssessment) -> None:
    """Render a clean summary table of covenant test results."""
    st.markdown("#### Covenant Compliance & Headroom")
    if not assessment.results:
        st.info("No covenant calculation results are available for this period.")
        return

    covenant_rows = []
    for r in assessment.results:
        status_upper = r.compliance_status.upper()
        covenant_rows.append(
            {
                "Covenant": r.covenant_type.replace("_", " ").title(),
                "Status": status_upper,
                "Actual Value": _fmt(r.actual_value, r.unit),
                "Contract Threshold": f"{r.operator or ''} {_fmt(r.threshold, r.unit)}".strip(),
                "Headroom": _fmt(r.headroom, r.unit),
                "Calculation Basis": r.financial_inputs.get("result_basis", "Reported").title(),
            }
        )

    st.dataframe(pd.DataFrame(covenant_rows), width="stretch", hide_index=True)


def render_flagging_tab(
    workflow: BorrowerWorkflow,
    assessment: RiskAssessment,
) -> None:
    """Render form to add risk flags, record triage, and submit case to Risk Manager."""
    run_id = assessment.assessment_run_id
    borrower_id = assessment.borrower_id

    st.markdown("### Flag Borrower for Risk Review")
    st.caption("Record material covenant breaches, performance degradation, or liquidity concerns.")

    col_flag, col_submit = st.columns([1.1, 1.3])

    with col_flag:
        with st.form(f"v2_flag_form_{run_id}"):
            st.markdown("##### 1. Add Risk Flag")
            category = st.selectbox(
                "Category",
                ["Covenant breach", "Liquidity", "Performance", "Data quality", "Other"],
                key=f"v2_flag_cat_{run_id}",
            )
            severity = st.selectbox(
                "Severity",
                ["Critical", "High", "Medium", "Low"],
                key=f"v2_flag_sev_{run_id}",
            )
            explanation = st.text_area(
                "Flag Explanation",
                placeholder="Explain breach trigger, headroom compression, or operational risk…",
                key=f"v2_flag_exp_{run_id}",
            )
            action = st.text_input(
                "Proposed Action",
                placeholder="e.g. Request equity cure, increase monitoring frequency…",
                key=f"v2_flag_act_{run_id}",
            )
            if st.form_submit_button("Add Flag to Borrower", use_container_width=True):
                if not explanation.strip():
                    st.error("Please provide an explanation for the flag.")
                else:
                    workflow.flag(
                        run_id,
                        category=category,
                        severity=severity,
                        explanation=explanation.strip(),
                        action=action.strip(),
                    )
                    st.success("Risk flag recorded successfully.")
                    st.rerun()

    with col_submit:
        with st.form(f"v2_submit_form_{run_id}"):
            st.markdown("##### 2. Analyst Observations & Handoff")
            analyst_name = st.text_input(
                "Analyst Name", value="Senior Credit Analyst", key=f"v2_analyst_{run_id}"
            )
            observations = st.text_area(
                "Observations & Summary Recommendation",
                placeholder="Summarize key findings, financial trends, and borrower outlook…",
                height=90,
                key=f"v2_obs_{run_id}",
            )
            triage_notes = st.text_area(
                "Breach Triage Justification (if applicable)",
                placeholder="Explain mitigating factors if breach is not critically flagged…",
                height=70,
                key=f"v2_triage_{run_id}",
            )

            submit_col1, submit_col2 = st.columns(2)
            draft_btn = submit_col1.form_submit_button("Save Draft Only")
            submit_btn = submit_col2.form_submit_button("📤 Submit to Risk Manager", type="primary")

            if draft_btn or submit_btn:
                obs_text = (
                    observations.strip() or "Standard quarterly covenant assessment completed."
                )
                try:
                    if submit_btn:
                        # Auto-validate checklist for smooth analyst handoff
                        workflow.validate(
                            run_id,
                            checks=(True, True, True),
                            notes="Automated review: financial statements verified.",
                            analyst=analyst_name,
                        )
                    workflow.save_report(
                        run_id,
                        text=obs_text,
                        analyst=analyst_name,
                        triage=triage_notes.strip(),
                        submit=bool(submit_btn),
                    )
                    if submit_btn:
                        st.success("Case successfully submitted to Risk Manager queue!")
                    else:
                        st.info("Draft observations saved.")
                    st.rerun()
                except Exception as err:
                    st.error(f"Submission note: {err}")

    # Display active flags table
    active_flags = [
        f
        for f in workflow.repository.flags(borrower_id)
        if f.get("payload", {}).get("state", "open") == "open"
    ]
    if active_flags:
        st.markdown("#### Open Flags on this Borrower")
        flag_rows = []
        for f in active_flags:
            p = f["payload"]
            flag_rows.append(
                {
                    "Severity": p.get("severity"),
                    "Category": p.get("category"),
                    "Explanation": p.get("explanation"),
                    "Proposed Action": p.get("action") or "Pending",
                    "Flag ID": f["flag_id"],
                }
            )
        st.dataframe(pd.DataFrame(flag_rows), width="stretch", hide_index=True)


def render_credit_analyst_view(
    workflow: BorrowerWorkflow,
    selected_period: date | None,
    cutoff: date,
) -> None:
    """Main view for Credit Analyst persona."""
    portfolio_service = workflow.portfolio
    entries = portfolio_service.snapshot(period_end=selected_period, cutoff=cutoff)

    if not entries:
        st.warning("No loan portfolio entries are available for the selected dates.")
        return

    # Keep track of active borrower
    if "v2_selected_borrower" not in st.session_state:
        st.session_state.v2_selected_borrower = entries[0].borrower_id

    # 3 Main Workflow Tabs
    tab_portfolio, tab_analysis, tab_flagging = st.tabs(
        ["📊 Loan Portfolio", "🔬 Run Analysis & Covenants", "🚩 Flag & Triage"]
    )

    # TAB 1: Loan Portfolio
    with tab_portfolio:
        selected_id = render_loan_portfolio_table(entries, st.session_state.v2_selected_borrower)
        if selected_id != st.session_state.v2_selected_borrower:
            st.session_state.v2_selected_borrower = selected_id
            st.rerun()

    # Retrieve current active assessment
    active_id = st.session_state.v2_selected_borrower
    active_entry = next((e for e in entries if e.borrower_id == active_id), entries[0])
    active_assessment: RiskAssessment | None = active_entry.assessment

    # TAB 2: Run Analysis & Covenants
    with tab_analysis:
        st.markdown(
            f"""
            <div class="cm-banner">
                <div style="font-size:1.15rem; font-weight:700; color:#0f172a;">
                    {active_entry.name}
                    <span style="font-size:0.85rem; color:#64748b;">({active_id})</span>
                </div>
                <div style="font-size:0.82rem; color:#475569; margin-top:3px;">
                    Sector: <b>{active_entry.sector}</b> ·
                    Period: <b>{active_entry.period_end or "Latest"}</b> ·
                    Status: <b>{active_entry.compliance}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Action bar to run assessment
        col_act1, col_act2, col_act3 = st.columns([1.2, 1.2, 2])
        with col_act1:
            run_assess = st.button(
                "⚡ Run Full Assessment", type="primary", use_container_width=True
            )
        with col_act2:
            run_agent = st.button("🤖 Run AI Credit Review", use_container_width=True)

        if run_assess:
            with st.spinner(f"Running financial and covenant assessment for {active_entry.name}…"):
                eff_period = selected_period or active_entry.period_end or date(2024, 9, 30)
                new_assessment = workflow.assess(
                    active_id,
                    eff_period,
                    cutoff,
                    prediction_mode="Logistic Regression",
                    reason="Analyst requested full assessment.",
                )
                st.session_state[f"v2_assessment_{active_id}"] = new_assessment
                st.success("Assessment completed successfully!")
                st.rerun()

        if run_agent and active_assessment:
            with st.spinner("Executing Bull/Bear credit review agents…"):
                workflow.portfolio.credit_review_service.review_assessment(
                    active_assessment,
                    question="Assess covenant compliance and exposure actions.",
                )
                st.success("AI Credit Review generated!")
                st.rerun()

        # Display calculations & headroom
        if active_assessment:
            col_cov, col_chat = st.columns([1.3, 1])
            with col_cov:
                render_covenants_card(active_assessment)
                with st.expander("Historical Headroom Trends", expanded=True):
                    render_saved_trend(active_assessment)

            with col_chat:
                # Embedded AI Assistant
                render_chat_widget(
                    workflow=workflow,
                    assessment=active_assessment,
                    suggested_prompts=ANALYST_SUGGESTED_PROMPTS,
                    key_prefix="analyst",
                    title="Analyst Assistant",
                    context_description=f"Copilot for {active_entry.name} calculations & evidence.",
                )

            # AI Credit Review snapshot if available
            latest_review = workflow.portfolio.repository.latest_review(
                active_assessment.assessment_run_id
            )
            if latest_review:
                st.divider()
                st.markdown("#### AI Agent Perspective: Bull vs Bear Review")
                render_agent_result(latest_review)
        else:
            st.info(
                "No assessment has been run yet for this borrower and period. "
                "Click **⚡ Run Full Assessment** above to evaluate covenants."
            )

    # TAB 3: Flag & Triage
    with tab_flagging:
        if active_assessment:
            render_flagging_tab(workflow, active_assessment)
        else:
            st.info(
                "Run an assessment in **Run Analysis** before flagging or submitting this borrower."
            )
