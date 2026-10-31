"""Connected risk manager queue, version comparison, decisions and analysis requests."""

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from credit_monitoring.application.board_reporting import BoardReporting
from credit_monitoring.application.manager_workflow import DEFAULT_CRITERIA, ManagerWorkflow
from credit_monitoring.application.portfolio_service import STATUS_LABELS
from credit_monitoring.web.assessment import render_evidence, render_results, render_verification
from credit_monitoring.web.borrower_analysis import get_workflow
from credit_monitoring.web.portfolio import formatted_time, render_agent_result
from credit_monitoring.web.review_requests import render_requests, run_action


def get_manager() -> ManagerWorkflow:
    return ManagerWorkflow(get_workflow())


def change_borrower() -> None:
    st.session_state.risk_saved_borrower = st.session_state.risk_borrower
    st.session_state.risk_queue_revision = st.session_state.get("risk_queue_revision", 0) + 1


def select_queue(widget_key: str, borrower_ids: tuple[str, ...]) -> None:
    selection = st.session_state[widget_key]["selection"]
    rows = tuple(selection.get("rows", []))
    cells = tuple(tuple(cell) for cell in selection.get("cells", []))
    previous = st.session_state.get("risk_queue_selection", {})
    if previous.get("key") != widget_key:
        previous = {}
    row = (
        cells[0][0]
        if cells and cells != previous.get("cells", ())
        else rows[0]
        if rows and rows != previous.get("rows", ())
        else None
    )
    if row is not None and 0 <= row < len(borrower_ids):
        st.session_state.risk_borrower = borrower_ids[row]
        st.session_state.risk_saved_borrower = borrower_ids[row]


def open_analyst(manager: ManagerWorkflow, borrower_id: str, submission: dict | None) -> None:
    st.session_state._analysis_open_borrower = borrower_id
    if submission:
        assessment = manager.assessment(submission)
        requests = manager.pending_requests(borrower_id)
        cutoff = max(
            [
                assessment.information_cutoff,
                *[date.fromisoformat(r["payload"]["review_cutoff"]) for r in requests],
            ]
        )
        st.session_state.analysis_saved_selection = {
            "borrower_id": borrower_id,
            "period": assessment.period_end.isoformat(),
            "cutoff": cutoff,
            "prediction_mode": "Logistic Regression",
        }
        for key in ("analysis_period", "analysis_cutoff", "analysis_version"):
            st.session_state.pop(key, None)
        st.session_state._analysis_next_run = assessment.assessment_run_id
    st.session_state._preview_next_page = "Borrower analysis"
    st.rerun()


def render_request_form(manager: ManagerWorkflow, submission: dict) -> None:
    assessment = manager.assessment(submission)
    sid = submission["submission_id"]
    with st.expander("Request another analysis"):
        with st.form(f"risk_request_{sid}"):
            kind = st.selectbox(
                "Request type",
                ["context", "correction"],
                format_func=lambda value: (
                    "Context-only credit review"
                    if value == "context"
                    else "Correct financials / terms and resubmit"
                ),
                key=f"risk_request_kind_{sid}",
            )
            question = st.text_input("Analysis question", key=f"risk_question_{sid}")
            context = st.text_area("Additional context / data", key=f"risk_context_{sid}")
            source = st.text_input("Source / reference (optional)", key=f"risk_source_{sid}")
            available = st.date_input(
                "Information available on (optional)", value=None, key=f"risk_available_{sid}"
            )
            cutoff = st.date_input(
                "Review information cutoff",
                assessment.information_cutoff,
                key=f"risk_review_cutoff_{sid}",
            )
            criteria = st.text_area(
                "Credit criteria", value="\n".join(DEFAULT_CRITERIA), key=f"risk_criteria_{sid}"
            )
            owner = st.text_input("Assigned analyst (optional)", key=f"risk_owner_{sid}")
            due = st.date_input("Due date", date.today() + timedelta(days=7), key=f"risk_due_{sid}")
            st.caption(
                "Unsourced claims remain assumptions. "
                "Later information requires an updated review cutoff. "
                "Context-only reviews run the three risk agents and generate follow-up questions; "
                "provider usage applies."
            )
            send, direct = st.columns(2)
            requested = send.form_submit_button("Send analysis request")
            run = direct.form_submit_button(
                "Run context-only review",
                disabled=not bool(os.getenv("OPENAI_API_KEY", "").strip()),
            )
            if requested or run:

                def request_action():
                    if run and kind != "context":
                        raise ValueError(
                            "Corrected inputs require analyst recalculation and resubmission."
                        )
                    rid = manager.request_analysis(
                        sid,
                        kind=kind,
                        question=question,
                        context=context,
                        source=source,
                        available_at=available,
                        review_cutoff=cutoff,
                        owner=owner,
                        due=due,
                        criteria=tuple(c.strip() for c in criteria.splitlines() if c.strip()),
                    )
                    if run:
                        with st.status("Running requested credit review…"):
                            manager.run_requested_review(rid)

                run_action(request_action, "Analysis request saved.")


def render_case(manager: ManagerWorkflow, borrower_id: str, period: date, cutoff: date) -> None:
    submissions = [
        s
        for s in manager.repository.submissions(borrower_id)
        if manager.assessment(s).period_end <= period
        and manager.assessment(s).information_cutoff <= cutoff
    ]
    if not submissions:
        st.info("No analyst submission is available for this borrower and reporting scope.")
        if st.button("Open borrower analysis", key="risk_open_analyst"):
            open_analyst(manager, borrower_id, None)
        for flag in manager.active_flags(borrower_id, period=period):
            st.write(f"{flag['payload']['severity']} · {flag['payload']['explanation']}")
        return
    lookup = {s["submission_id"]: s for s in submissions}
    key = f"risk_submission_{borrower_id}"
    if st.session_state.get(key) not in lookup:
        st.session_state[key] = submissions[0]["submission_id"]
    sid = st.selectbox(
        "Submitted version",
        list(lookup),
        key=key,
        format_func=lambda value: (
            f"{manager.assessment(lookup[value]).period_end} · "
            f"{formatted_time(lookup[value]['created_at'])} · {value}"
        ),
    )
    submission = lookup[sid]
    assessment = manager.assessment(submission)
    current = manager.current_review(submission)
    st.caption(
        f"Assessment {assessment.assessment_run_id} · Reporting period {assessment.period_end} · "
        f"Assessment cutoff {assessment.information_cutoff} · {manager.state(submission)}"
    )
    if st.button("Open borrower analysis", key="risk_open_analyst"):
        open_analyst(manager, borrower_id, submission)
    if current:
        render_agent_result(current)
        if current.snapshot.review_information_cutoff:
            st.caption(f"Credit review cutoff {current.snapshot.review_information_cutoff}")
        if current.snapshot.additional_context_json != "[]":
            st.json(current.snapshot.prompt_context()["additional_context"], expanded=False)
    else:
        st.info(
            "Credit analysis pending. Saved calculations and analyst observations remain available."
        )
    if manager.state(submission) not in {"Pending review", "Reviewed"}:
        st.warning(manager.state(submission))
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("Analyst handoff")
        st.write(submission["payload"]["text"])
        st.caption(f"Analyst: {submission['payload']['analyst'] or 'Unspecified'}")
        notes = submission["payload"]["validation"]["payload"]
        st.write(notes["notes"] or "No validation exceptions recorded.")
        if submission["payload"]["triage"]:
            st.write(f"Triage: {submission['payload']['triage']}")
        for flag in submission["payload"]["flags"]:
            st.markdown(f"**{flag['payload']['severity']} · {flag['payload']['category']}**")
            st.write(flag["payload"]["explanation"])
            st.caption(flag["payload"]["action"] or "Proposed action pending.")
    with right:
        st.subheader("Your review")
        previous = next(
            (
                n["payload"]
                for n in manager.repository.notes(borrower_id)
                if n["submission_id"] == sid
            ),
            {},
        )
        with st.form(f"risk_decision_{sid}_{current.review_id if current else 'none'}"):
            reviewer = st.text_input("Manager name (optional)", value=previous.get("manager", ""))
            comment = st.text_area(
                "Manager observations", value=previous.get("comment", ""), key=f"risk_comment_{sid}"
            )
            recommendation = st.text_area(
                "Recommendation",
                value=previous.get("recommendation", ""),
                key=f"risk_recommendation_{sid}",
            )
            disposition = st.selectbox(
                "Next step",
                ["Continue monitoring", "Request remediation", "Resolve selected flags"],
                key=f"risk_disposition_{sid}",
            )
            submitted_ids = {f["flag_id"] for f in submission["payload"]["flags"]}
            resolvable = {
                f["flag_id"]: f
                for f in manager.active_flags(borrower_id)
                if f["flag_id"] in submitted_ids
            }
            resolve = st.multiselect(
                "Flags to resolve",
                list(resolvable),
                format_func=lambda fid: resolvable[fid]["payload"]["explanation"],
                key=f"risk_resolve_{sid}",
            )
            save, finish = st.columns(2)
            save_clicked = save.form_submit_button("Save comment")
            reviewed = finish.form_submit_button("Mark reviewed", type="primary")
            if save_clicked or reviewed:
                run_action(
                    lambda: manager.record_note(
                        sid,
                        comment=comment,
                        recommendation=recommendation,
                        manager=reviewer,
                        reviewed=reviewed,
                        disposition=disposition,
                        resolve_ids=resolve if reviewed else [],
                    ),
                    "Manager review saved.",
                )
    render_request_form(manager, submission)
    st.subheader("Analysis requests and responses")
    render_requests(manager, borrower_id)
    with st.expander("Calculations, verification and source evidence"):
        render_results(assessment)
        render_verification(assessment)
        render_evidence(assessment)
    with st.expander("Previous credit reviews and manager decisions"):
        for review in manager.portfolio.repository.review_history(assessment.assessment_run_id):
            st.caption(f"Review {review.review_id} · {review.created_at.isoformat()}")
            render_agent_result(review)
        for note in manager.repository.notes(borrower_id):
            st.caption(f"Manager note {note['note_id']} · {note['created_at']}")
            st.json(note["payload"], expanded=False)


def render_risk_review_page() -> None:
    from credit_monitoring.web.user_guide import render_help

    st.title("Risk review")
    render_help(
        "Documents, manager and board workflows", "How to review and request another analysis"
    )
    st.caption("Review saved analyst submissions, request further analysis and record a decision.")
    try:
        manager = get_manager()
        periods = manager.portfolio.periods()
    except Exception as error:
        st.error(f"Could not open risk review ({type(error).__name__}).")
        return
    names = {b["borrower_id"]: b["borrower_name"] for b in manager.portfolio.borrowers}
    if not names:
        st.info("No borrowers are registered.")
        return
    dates, cutoffs = st.columns(2)
    selected = dates.selectbox(
        "Reporting period",
        ["latest", *[p.isoformat() for p in reversed(periods)]],
        format_func=lambda value: "Latest available per borrower" if value == "latest" else value,
        key="risk_period",
    )
    cutoff = cutoffs.date_input(
        "Information cutoff", periods[-1] if periods else date.today(), key="risk_cutoff"
    )
    period = None if selected == "latest" else date.fromisoformat(selected)
    if period and cutoff < period:
        st.error("Information cutoff must be on or after the reporting period.")
        return
    entries = manager.portfolio.snapshot(period_end=period, cutoff=cutoff)
    scope_period = period or cutoff
    sources = BoardReporting(manager).sources(scope_period, cutoff)
    if st.session_state.get("risk_borrower") not in names:
        prior = (
            st.session_state.get("risk_saved_borrower")
            or st.session_state.get("analysis_saved_selection", {}).get("borrower_id")
            or st.session_state.get("portfolio_borrower")
        )
        st.session_state.risk_borrower = prior if prior in names else next(iter(names))
    borrower_id = st.selectbox(
        "Select borrower to review",
        list(names),
        format_func=names.get,
        key="risk_borrower",
        on_change=change_borrower,
    )
    columns = st.columns(6)
    for column, label, value in zip(
        columns,
        [
            "Borrowers",
            "Assessed",
            "Not assessed",
            "Breaches",
            "Flagged borrowers",
            "Pending reviews",
        ],
        [
            len(entries),
            sum(e.assessment is not None for e in entries),
            sum(e.assessment is None for e in entries),
            sum("breach" in e.statuses for e in entries),
            sources["metrics"]["flagged_borrowers"],
            sources["metrics"]["pending_reviews"],
        ],
        strict=True,
    ):
        column.metric(label, value)
    st.caption(
        "Count-based metrics use saved results. "
        "Waived, not-tested and incomplete statuses stay distinct."
    )
    st.subheader("Flagged borrowers and submitted reports")
    view = st.radio(
        "Queue view",
        ["All cases", "Needs attention", "Reviewed"],
        horizontal=True,
        key="risk_queue_filter",
    )
    scope_ids = {item["borrower_id"] for item in sources["items"]}
    scope_ids.update(
        s["borrower_id"]
        for s in manager.repository.submissions()
        if manager.assessment(s).period_end <= scope_period
        and manager.assessment(s).information_cutoff <= cutoff
    )
    items = {item["borrower_id"]: item for item in sources["items"]}
    rows = []
    for bid in sorted(scope_ids):
        submission = manager.latest_submission(bid, period=scope_period, cutoff=cutoff)
        item = items.get(bid, {})
        state = (
            manager.state(submission)
            if submission
            else (
                "Untriaged breach" if item.get("untriaged_breach") else "Analyst submission pending"
            )
        )
        if (
            view == "Reviewed"
            and state != "Reviewed"
            or view == "Needs attention"
            and state == "Reviewed"
        ):
            continue
        raw = submission["payload"]["assessment"] if submission else item.get("assessment")
        rows.append(
            {
                "Borrower": names.get(bid, bid),
                "ID": bid,
                "Review": state,
                "Compliance": " / ".join(
                    sorted({STATUS_LABELS[r["compliance_status"]] for r in raw["results"]})
                )
                if raw and raw["results"]
                else "Incomplete"
                if raw
                else "Not assessed",
                "Severity": max(
                    (f["payload"]["severity"] for f in item.get("flags", [])),
                    key=lambda value: {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}[value],
                    default="Untriaged" if item.get("untriaged_breach") else "Not flagged",
                ),
                "Analyst": submission["payload"]["analyst"] or "Unspecified"
                if submission
                else "Not submitted",
                "Period": raw["period_end"] if raw else "No assessment at cutoff",
                "Open flags": len(manager.active_flags(bid, period=scope_period)),
                "Explanation": "; ".join(f["payload"]["explanation"] for f in item.get("flags", []))
                or (
                    "Breach requires triage"
                    if item.get("untriaged_breach")
                    else "Analyst report submitted"
                ),
            }
        )
    if rows:
        key = f"risk_queue_{st.session_state.get('risk_queue_revision', 0)}_" + "_".join(
            r["ID"] for r in rows
        )
        ids = tuple(r["ID"] for r in rows)
        event = st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            key=key,
            selection_mode=["single-row", "single-cell"],
            on_select=lambda: select_queue(key, ids),
        )
        st.session_state.risk_queue_selection = {
            "key": key,
            "rows": tuple(event.selection.rows),
            "cells": tuple(tuple(c) for c in event.selection.cells),
        }
    else:
        st.info("No cases match this queue. Assess and submit a borrower from Borrower analysis.")
    if st.button("Prepare board report", key="risk_open_board"):
        st.session_state._preview_next_page = "Board report"
        st.rerun()
    st.header(names[borrower_id])
    render_case(manager, borrower_id, scope_period, cutoff)
