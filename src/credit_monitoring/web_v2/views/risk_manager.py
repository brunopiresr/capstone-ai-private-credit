"""Risk Manager View: Flagged queue, sign-off, board report studio, and Risk Copilot chat."""

from datetime import date

import pandas as pd
import streamlit as st

from credit_monitoring.application.board_reporting import BoardReporting
from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.application.manager_workflow import ManagerWorkflow
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.web.portfolio import formatted_time
from credit_monitoring.web.telemetry import with_web_session
from credit_monitoring.web_v2.components.chat import render_chat_widget
from credit_monitoring.web_v2.components.metrics import render_kpi_card


def _fmt(value: float | None, unit: str | None = None) -> str:
    """Format a numeric value safely; returns '—' if value is None."""
    if value is None:
        return "—"
    return f"{value:.2f}{unit or ''}"


RISK_COPILOT_SUGGESTED_PROMPTS = [
    "Summarize all Critical flags for the board",
    "Which borrowers have untriaged breaches?",
    "Draft an executive summary bullet for the board report",
    "Compare leverage and headroom across flagged borrowers",
]

RISK_TABS = ["⚠️ Flagged Borrowers Queue", "✍️ Review & Sign-Off", "📑 Board Report Studio"]


def _open_queue_review(borrower_ids: tuple[str, ...]) -> None:
    """Route a queue button click using the displayed dataframe's row order."""
    click = st.session_state.get("v2_risk_review_click")
    if click is None:
        return
    row = click["row"]
    if 0 <= row < len(borrower_ids):
        st.session_state.v2_risk_selected_borrower = borrower_ids[row]
        st.session_state.v2_risk_tabs = RISK_TABS[1]


def render_flagged_queue_table(
    items: list[dict],
) -> None:
    """Render priority queue table of flagged borrowers and untriaged breaches."""
    st.markdown("### Priority Exception Queue")
    if not items:
        st.info(
            "No flagged borrowers or covenant breaches requiring triage in this reporting scope."
        )
        return

    rows = []
    for item in items:
        bid = item["borrower_id"]
        flags = item.get("flags", [])
        severity = max(
            (f["payload"]["severity"] for f in flags),
            key=lambda v: {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}.get(v, 0),
            default="Critical" if item.get("untriaged_breach") else "Untriaged",
        )
        status_str = (
            "Untriaged Breach"
            if item.get("untriaged_breach")
            else item.get("review_state", "Pending")
        )

        rows.append(
            {
                "Review": "Review",
                "Borrower": item["name"],
                "ID": bid,
                "Priority": severity,
                "Review State": status_str,
                "Open Flags": len(flags),
                "Category": flags[0]["payload"]["category"] if flags else "Covenant Breach",
                "Explanation": "; ".join(f["payload"]["explanation"] for f in flags)
                or "Covenant breach awaiting triage",
                "Recommendation": item.get("recommendation") or "Pending Review",
            }
        )

    df = pd.DataFrame(rows)
    # Sort priority: Critical -> High -> Medium -> Low
    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Untriaged": 4}
    df["sort_key"] = df["Priority"].map(lambda p: priority_order.get(p, 5))
    df = df.sort_values("sort_key", kind="stable").drop(columns=["sort_key"]).reset_index(drop=True)

    key = "v2_risk_queue_table"
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        key=key,
        column_config={
            "Review": st.column_config.ButtonColumn(
                "Action",
                width="small",
                pinned=True,
                help="Open this borrower's review and sign-off.",
                key="v2_risk_review_click",
                on_click=with_web_session(_open_queue_review),
                args=(tuple(df["ID"]),),
            ),
        },
    )


def render_manager_signoff_panel(
    manager: ManagerWorkflow,
    item: dict,
    scope_period: date,
    cutoff: date,
) -> None:
    """Render detailed review of analyst submission and record manager decisions."""
    bid = item["borrower_id"]
    submission = manager.latest_submission(bid, period=scope_period, cutoff=cutoff)
    assessment_data = item.get("assessment")
    assessment = RiskAssessment.model_validate(assessment_data) if assessment_data else None

    st.markdown(
        f"""
        <div class="cm-banner">
            <div style="font-size:1.15rem; font-weight:700; color:#0f172a;">
                Case Dossier: {item["name"]}
                <span style="font-size:0.85rem; color:#64748b;">({bid})</span>
            </div>
            <div style="font-size:0.82rem; color:#475569; margin-top:3px;">
                Review State: <b>{item.get("review_state")}</b> ·
                Cutoff: <b>{cutoff}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_details, col_decision = st.columns([1.2, 1])

    with col_details:
        st.markdown("#### Analyst Findings & Covenants")
        if submission:
            payload = submission["payload"]
            st.markdown(f"**Analyst Observations:** {payload.get('text', 'No notes provided.')}")
            if payload.get("triage"):
                st.markdown(f"**Triage Rationale:** {payload.get('triage')}")
            analyst_label = payload.get("analyst", "Unspecified")
            created_label = formatted_time(submission.get("created_at"))
            st.caption(f"Submitted by: {analyst_label} on {created_label}")
        else:
            st.warning("No formal analyst submission on file for this reporting period.")

        if assessment:
            st.markdown("##### Calculated Covenants")
            cov_rows = [
                {
                    "Covenant": r.covenant_type.replace("_", " ").title(),
                    "Status": r.compliance_status.upper(),
                    "Actual": _fmt(r.actual_value, r.unit),
                    "Limit": f"{r.operator or ''} {_fmt(r.threshold, r.unit)}".strip(),
                    "Headroom": _fmt(r.headroom),
                }
                for r in assessment.results
            ]
            st.dataframe(pd.DataFrame(cov_rows), width="stretch", hide_index=True)

        # Show open flags
        flags = item.get("flags", [])
        if flags:
            st.markdown("##### Active Risk Flags")
            for f in flags:
                p = f["payload"]
                st.markdown(
                    f"- **[{p.get('severity')}] {p.get('category')}**: {p.get('explanation')}"
                )
                if p.get("action"):
                    st.caption(f"  Proposed Action: {p.get('action')}")

    with col_decision:
        st.markdown("#### Manager Governance Sign-Off")
        notes = manager.repository.notes(bid)
        prior_note = notes[0]["payload"] if notes else {}

        with st.form(f"v2_manager_decision_{bid}"):
            reviewer = st.text_input(
                "Risk Manager Name", value=prior_note.get("manager", "Credit Risk Director")
            )
            comment = st.text_area(
                "Risk Committee / Manager Observations",
                value=prior_note.get("comment", ""),
                placeholder="Enter governance comments, waiver terms, or committee findings…",
                height=90,
            )
            recommendation = st.text_area(
                "Board-Facing Recommendation",
                value=prior_note.get("recommendation", item.get("recommendation", "")),
                placeholder="e.g. Issue 60-day reservation of rights letter; request audit.",
                height=70,
            )
            disposition = st.selectbox(
                "Governance Action",
                ["Continue monitoring", "Request remediation", "Resolve selected flags"],
            )

            # Flags that can be resolved
            resolvable_flags = {
                f["flag_id"]: f["payload"]["explanation"] for f in item.get("flags", [])
            }
            flags_to_resolve = st.multiselect(
                "Select Flags to Resolve (if disposition permits)",
                options=list(resolvable_flags.keys()),
                format_func=lambda fid: resolvable_flags[fid],
            )

            btn_save, btn_sign = st.columns(2)
            save_clicked = btn_save.form_submit_button("Save Notes")
            sign_clicked = btn_sign.form_submit_button("✅ Mark Reviewed", type="primary")

            if save_clicked or sign_clicked:
                if submission:
                    manager.record_note(
                        submission["submission_id"],
                        comment=comment.strip(),
                        recommendation=recommendation.strip(),
                        manager=reviewer.strip(),
                        reviewed=bool(sign_clicked),
                        disposition=disposition,
                        resolve_ids=flags_to_resolve if sign_clicked else [],
                        review_cutoff=cutoff,
                    )
                    st.success("Manager review recorded successfully!")
                    st.rerun()
                else:
                    st.error("Cannot mark reviewed without an active analyst submission.")

        # Request another analysis expander
        with st.expander("Request Follow-Up Analysis from Analyst"):
            with st.form(f"v2_req_analysis_{bid}"):
                question = st.text_input(
                    "Follow-Up Question",
                    placeholder="e.g. Re-evaluate EBITDA excluding inventory write-downs",
                )
                owner = st.text_input("Assign to Analyst", value="Senior Credit Analyst")
                if st.form_submit_button("Send Analysis Request"):
                    if submission and question.strip():
                        manager.request_analysis(
                            submission["submission_id"],
                            kind="context",
                            question=question.strip(),
                            context="Risk Manager request for clarification.",
                            owner=owner.strip(),
                            due=date.today(),
                            review_cutoff=cutoff,
                        )
                        st.success("Analysis request dispatched to analyst!")
                        st.rerun()
                    elif not submission:
                        st.error("Submission required to dispatch follow-up.")


def render_board_report_studio(
    manager: ManagerWorkflow,
    scope_period: date,
    cutoff: date,
) -> None:
    """Render the Board Report Generator, Executive Summary editor, and Finalization snapshot."""
    reporting = BoardReporting(manager)
    reports = manager.repository.board_reports()
    report_lookup = {r["report_id"]: r for r in reports}

    # Apply generated-report navigation before instantiating the selector widget.
    generated_report_id = st.session_state.pop("_v2_board_next_report", None)
    if generated_report_id in report_lookup:
        st.session_state.v2_board_report_select = generated_report_id
        st.success(f"Report draft {generated_report_id} generated!")

    st.markdown("### Board Report Studio")
    st.caption("Generate, edit, and freeze formal quarterly credit risk reports for the Board.")

    # Selector for report
    report_options = ["new", *report_lookup.keys()]

    def format_report_option(rid: str) -> str:
        if rid == "new":
            return "➕ Generate New Report Draft"
        rec = report_lookup[rid]
        title_str = rec["payload"]["title"]
        state_str = rec["state"].title()
        time_str = formatted_time(rec["created_at"])
        return f"{title_str} ({state_str} - {time_str})"

    selected_report_id = st.selectbox(
        "Select Report Version",
        report_options,
        format_func=format_report_option,
        key="v2_board_report_select",
    )

    if selected_report_id == "new":
        st.markdown("#### Generate New Board Report Draft")
        title = st.text_input(
            "Report Title", value="Quarterly Credit Risk & Exception Review", key="v2_new_title"
        )
        if st.button("Generate Draft from Current Portfolio", type="primary"):
            new_id = reporting.generate(scope_period, cutoff, title=title)
            st.session_state._v2_board_next_report = new_id
            st.rerun()
        return

    # Render active report
    report = report_lookup[selected_report_id]
    payload = report["payload"]
    sources = payload["sources"]
    is_final = report["state"] == "final"

    if is_final:
        st.success("🔒 Finalized snapshot. Data and recommendations are locked for the Board.")
    else:
        st.info("✏️ Draft Version. You can edit the executive summary & recommendations below.")

    # KPI summary for board
    metrics = sources["metrics"]
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_kpi_card("Total Borrowers", metrics["borrowers"], "In scope")
    with m2:
        render_kpi_card("Flagged Loans", metrics["flagged_borrowers"], "Requiring disclosure")
    with m3:
        render_kpi_card("Untriaged Breaches", metrics["untriaged_breaches"], "Urgent exceptions")
    with m4:
        render_kpi_card("Pending Reviews", metrics["pending_reviews"], "Awaiting sign-off")

    st.markdown("#### Executive Summary")
    if is_final:
        st.markdown(f"> {payload['summary']}")
    else:
        new_summary = st.text_area(
            "Executive Summary",
            value=payload["summary"],
            height=130,
            key=f"v2_rep_sum_{selected_report_id}",
        )

    # Exception Register Table
    st.markdown("#### Board Exception Register")
    items = sources.get("items", [])
    if items:
        reg_rows = []
        for it in items:
            flags = it.get("flags", [])
            sev = max(
                (f["payload"]["severity"] for f in flags),
                key=lambda v: {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}.get(v, 0),
                default="Critical" if it.get("untriaged_breach") else "Untriaged",
            )
            reg_rows.append(
                {
                    "Borrower": it["name"],
                    "ID": it["borrower_id"],
                    "Priority": sev,
                    "Breach / Issue": "; ".join(f["payload"]["explanation"] for f in flags)
                    or "Covenant breach",
                    "Manager Recommendation": payload["recommendations"].get(
                        it["borrower_id"], it.get("recommendation", "Continue monitoring")
                    ),
                }
            )
        st.dataframe(pd.DataFrame(reg_rows), width="stretch", hide_index=True)
    else:
        st.info("No exceptions registered for this reporting period.")

    # Form actions if draft
    if not is_final:
        st.markdown("#### Edit Borrower Recommendations")
        rec_edits = {}
        for it in items:
            bid = it["borrower_id"]
            rec_edits[bid] = st.text_input(
                f"Recommendation for {it['name']}",
                value=payload["recommendations"].get(bid, it.get("recommendation", "")),
                key=f"v2_rec_{selected_report_id}_{bid}",
            )

        col_save, col_ref, col_fin = st.columns(3)
        if col_save.button("💾 Save Draft Updates"):
            reporting.save(
                selected_report_id,
                title=payload["title"],
                summary=new_summary,
                recommendations=rec_edits,
                finalize=False,
            )
            st.success("Draft saved.")
            st.rerun()
        if col_ref.button("🔄 Refresh Draft Sources"):
            reporting.save(
                selected_report_id,
                title=payload["title"],
                summary=new_summary,
                recommendations=rec_edits,
                refresh=True,
            )
            st.success("Sources refreshed with latest borrower data.")
            st.rerun()
        if col_fin.button("🔒 Finalize & Snapshot for Board", type="primary"):
            reporting.save(
                selected_report_id,
                title=payload["title"],
                summary=new_summary,
                recommendations=rec_edits,
                finalize=True,
            )
            st.success("Report finalized! Snapshot is permanently frozen.")
            st.rerun()


def render_risk_manager_view(
    workflow: BorrowerWorkflow,
    selected_period: date | None,
    cutoff: date,
) -> None:
    """Main view for Risk Manager persona."""
    manager = ManagerWorkflow(workflow)
    scope_period = selected_period or cutoff
    sources = BoardReporting(manager).sources(scope_period, cutoff)
    items = sources.get("items", [])
    metrics = sources["metrics"]

    # 1. Manager KPI bar
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_kpi_card("Flagged Borrowers", metrics["flagged_borrowers"], "Active risk cases")
    with col2:
        render_kpi_card(
            "Untriaged Breaches", metrics["untriaged_breaches"], "Awaiting analyst triage"
        )
    with col3:
        render_kpi_card("Pending Reviews", metrics["pending_reviews"], "Requires sign-off")
    with col4:
        render_kpi_card("Total Monitored", metrics["borrowers"], "In reporting scope")

    # Active flagged borrower selection
    names = {item["borrower_id"]: f"{item['name']} ({item['borrower_id']})" for item in items}
    if st.session_state.get("v2_risk_selected_borrower") not in names:
        st.session_state.v2_risk_selected_borrower = items[0]["borrower_id"] if items else ""

    # Stateful tabs let the queue action open the review without losing other navigation.
    tab_queue, tab_review, tab_board = st.tabs(RISK_TABS, key="v2_risk_tabs", on_change="rerun")

    # TAB 1: Flagged Queue
    with tab_queue:
        render_flagged_queue_table(items)

    # TAB 2: Review & Sign-Off
    with tab_review:
        if items:
            selected_bid = st.selectbox(
                "Select Flagged Borrower to Review or Sign-Off",
                options=list(names),
                format_func=names.get,
                key="v2_risk_selected_borrower",
            )
            selected_item = next(item for item in items if item["borrower_id"] == selected_bid)
            render_manager_signoff_panel(manager, selected_item, scope_period, cutoff)

            # Embedded Risk Copilot for the selected borrower / portfolio
            assessment_data = selected_item.get("assessment")
            assessment = RiskAssessment.model_validate(assessment_data) if assessment_data else None

            st.divider()
            render_chat_widget(
                workflow=workflow,
                assessment=assessment,
                suggested_prompts=RISK_COPILOT_SUGGESTED_PROMPTS,
                key_prefix="risk_copilot",
                title="Risk Copilot",
                context_description=(
                    "Portfolio & governance assistant for flags and board reporting."
                ),
            )
        else:
            st.info(
                "No flagged borrowers are available for review in this reporting scope. "
                "Choose another reporting period or information cutoff."
            )

    # TAB 3: Board Report Studio
    with tab_board:
        render_board_report_studio(manager, scope_period, cutoff)
