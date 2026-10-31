"""Saved board report drafts, source refresh, final snapshots and direct report links."""

from datetime import date

import pandas as pd
import streamlit as st

from credit_monitoring.application.board_reporting import BoardReporting
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import CreditReviewResult
from credit_monitoring.web.portfolio import formatted_time, render_agent_result
from credit_monitoring.web.review_requests import run_action
from credit_monitoring.web.risk_review import get_manager


def select_report(report_id: str) -> None:
    st.session_state._board_next_report = report_id
    st.query_params["report_id"] = report_id


def change_report_selection() -> None:
    report_id = st.session_state.board_report_selection
    if report_id == "new":
        st.query_params.pop("report_id", None)
        st.session_state._board_link_seen = None
    else:
        st.query_params["report_id"] = report_id


def render_report_content(report: dict) -> None:
    payload = report["payload"]
    sources = payload["sources"]
    st.header(payload["title"])
    st.caption(
        f"Period ending {sources['period']} · Information cutoff {sources['cutoff']} · "
        f"Saved {formatted_time(report['created_at'])} · {report['state'].title()} "
        f"· {report['report_id']}"
    )
    metrics = sources["metrics"]
    columns = st.columns(5)
    for column, label, value in zip(
        columns,
        ["Borrowers", "Flagged borrowers", "Untriaged breaches", "Pending reviews", "Not assessed"],
        [
            metrics["borrowers"],
            metrics["flagged_borrowers"],
            metrics["untriaged_breaches"],
            metrics["pending_reviews"],
            metrics["unassessed"],
        ],
        strict=True,
    ):
        column.metric(label, value)
    st.caption(
        f"{metrics['data_gaps']} assessed borrowers have data gaps; "
        f"{metrics['missing_credit_analysis']} reported cases lack complete credit analysis."
    )
    st.subheader("Executive summary")
    st.write(payload["summary"])
    if sources["pending_submissions"]:
        st.subheader("Pending analyst submissions / manager reviews")
        st.dataframe(pd.DataFrame(sources["pending_submissions"]), hide_index=True, width="stretch")
    st.subheader("Complete flagged register and untriaged breaches")
    rows = []
    for item in sources["items"]:
        assessment = item["assessment"]
        severity = max(
            (f["payload"]["severity"] for f in item["flags"]),
            key=lambda value: {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}[value],
            default="Untriaged",
        )
        rows.append(
            {
                "Borrower": item["name"],
                "ID": item["borrower_id"],
                "Priority": severity,
                "Assessment period": assessment["period_end"]
                if assessment
                else "Unavailable at cutoff",
                "Flag periods": ", ".join(sorted({f["assessment_period"] for f in item["flags"]})),
                "Review": item["review_state"],
                "Explanation": "; ".join(f["payload"]["explanation"] for f in item["flags"])
                or "Breach awaiting analyst triage",
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No open flags or untriaged breaches are in this reporting scope.")
    for item in sources["items"]:
        with st.container(border=True):
            st.subheader(item["name"])
            st.caption(f"{item['borrower_id']} · {item['review_state']}")
            if item["untriaged_breach"]:
                st.warning("Untriaged breach: a flag or explained triage decision is pending.")
            for flag in item["flags"]:
                st.markdown(f"**{flag['payload']['severity']} · {flag['payload']['category']}**")
                st.write(flag["payload"]["explanation"])
                st.caption(f"Flag assessment {flag['assessment_period']} · {flag['run_id']}")
                st.write("Proposed action: " + (flag["payload"]["action"] or "Pending"))
            if item["assessment"]:
                assessment = RiskAssessment.model_validate(item["assessment"])
                st.caption(
                    f"Assessment {assessment.assessment_run_id} · Period {assessment.period_end} · "
                    f"Cutoff {assessment.information_cutoff} "
                    f"· Saved {formatted_time(item['assessment_created_at'])}"
                )
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Covenant": r.covenant_type,
                                "Compliance": r.compliance_status,
                                "Actual": r.actual_value,
                                "Threshold": r.threshold,
                                "Headroom": r.headroom,
                                "Unit": r.unit,
                            }
                            for r in assessment.results
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
                for issue in assessment.issues:
                    st.caption(issue)
            else:
                st.warning("No saved assessment is available at the report cutoff.")
            st.markdown("**Risk analysis, mitigants and bull/bear conclusions**")
            if item["review"]:
                render_agent_result(CreditReviewResult.model_validate(item["review"]))
            else:
                st.info("Credit analysis and mitigants pending.")
            st.markdown("**Analyst observations**")
            st.write(
                item["submission"]["payload"]["text"]
                if item["submission"]
                else "Analyst submission pending."
            )
            if item["submission"]:
                st.caption(f"Submission {item['submission']['submission_id']}")
                notes = item["submission"]["payload"]["validation"]["payload"]["notes"]
                if notes:
                    st.write(notes)
            st.markdown("**Manager recommendation**")
            edited = payload["recommendations"].get(item["borrower_id"], "").strip()
            st.write(edited or item["recommendation"])
            if item["manager_note"]:
                st.caption(item["manager_note"]["payload"]["comment"])
            elif item["review_state"] != "Reviewed":
                st.caption(
                    "Manager sign-off remains pending even when "
                    "a board-facing recommendation is supplied."
                )
            for request in item["requests"]:
                if request["state"] not in {"accepted", "cancelled"}:
                    st.write(
                        f"Outstanding: {request['payload']['question']} · "
                        f"{request['state']} · Due {request['payload']['due'] or 'Unspecified'}"
                    )


def render_board_report_page() -> None:
    from credit_monitoring.web.user_guide import render_help

    st.title("Board report")
    render_help(
        "Documents, manager and board workflows", "How to prepare and finalize a board report"
    )
    st.caption("Prepare a complete exception register and save a report whose sources stay frozen.")
    try:
        manager = get_manager()
        reporting = BoardReporting(manager)
        reports = manager.repository.board_reports()
    except Exception as error:
        st.error(f"Could not open board reports ({type(error).__name__}).")
        return
    lookup = {r["report_id"]: r for r in reports}
    next_report = st.session_state.pop("_board_next_report", None)
    linked_report = st.session_state.pop("_board_open_report", None)
    pending = next_report or linked_report
    if pending:
        if pending not in lookup:
            st.error("Saved board report was not found.")
        else:
            st.session_state.board_report_selection = pending
    if st.session_state.get("board_report_selection") not in {"new", *lookup}:
        remembered = st.session_state.get("board_saved_selection", "new")
        st.session_state.board_report_selection = remembered if remembered in lookup else "new"
    selected = st.selectbox(
        "Report",
        ["new", *lookup],
        key="board_report_selection",
        on_change=change_report_selection,
        format_func=lambda rid: (
            "Create a new report"
            if rid == "new"
            else f"{lookup[rid]['payload']['title']} · {lookup[rid]['state'].title()} "
            f"· {formatted_time(lookup[rid]['created_at'])} · {rid}"
        ),
    )
    st.session_state.board_saved_selection = selected
    if selected == "new":
        periods = sorted(
            set(manager.portfolio.periods())
            | {a.period_end for a in manager.portfolio.repository.all_assessments()}
        )
        if not periods:
            st.info(
                "No reporting periods are available. Assess a borrower before preparing a report."
            )
            return
        with st.form("board_generate"):
            title = st.text_input(
                "Report title", value="Quarterly credit risk review", key="board_title_new"
            )
            period = st.selectbox(
                "Reporting period", [p.isoformat() for p in reversed(periods)], key="board_period"
            )
            cutoff = st.date_input("Information cutoff", periods[-1], key="board_cutoff")
            if st.form_submit_button("Generate report draft", type="primary"):
                run_action(
                    lambda: select_report(
                        reporting.generate(date.fromisoformat(period), cutoff, title=title)
                    ),
                    "Board report draft saved.",
                )
        return
    report = lookup[selected]
    payload = report["payload"]
    if report["state"] == "final":
        st.success(
            "Finalized report. Later assessments, flags and decisions do not change this snapshot."
        )
        st.code(f"?report_id={selected}", language=None)
        render_report_content(report)
        return
    st.info(
        "Saved draft. Refresh sources after case changes before finalizing. "
        "Missing recommendations remain pending."
    )
    with st.form(f"board_edit_{selected}"):
        title = st.text_input("Report title", value=payload["title"], key=f"board_title_{selected}")
        summary = st.text_area(
            "Executive summary",
            value=payload["summary"],
            height=130,
            key=f"board_summary_{selected}",
        )
        recommendations = {}
        for item in payload["sources"]["items"]:
            bid = item["borrower_id"]
            recommendations[bid] = st.text_area(
                f"Recommendation · {item['name']}",
                value=payload["recommendations"].get(bid, item["recommendation"]),
                key=f"board_recommendation_{selected}_{bid}",
            )
        save, refresh, final = st.columns(3)
        save_clicked = save.form_submit_button("Save report draft")
        refresh_clicked = refresh.form_submit_button("Refresh draft sources")
        finalize = final.form_submit_button("Finalize report", type="primary")
        if save_clicked or refresh_clicked or finalize:
            run_action(
                lambda: select_report(
                    reporting.save(
                        selected,
                        title=title,
                        summary=summary,
                        recommendations=recommendations,
                        finalize=finalize,
                        refresh=refresh_clicked,
                    )
                ),
                "Report finalized." if finalize else "Draft version saved.",
            )
    render_report_content(report)
