"""Separate exception queue and case pages; decisions use existing version-bound services."""

from datetime import date, timedelta

import streamlit as st

from credit_monitoring.application.manager_workflow import DEFAULT_CRITERIA
from credit_monitoring.web.assessment import render_evidence, render_verification
from credit_monitoring.web.borrower_views import render_covenant_table
from credit_monitoring.web.portfolio import formatted_time, render_agent_result
from credit_monitoring.web_v3.analyst import credentials
from credit_monitoring.web_v3.checklist import checklist_states
from credit_monitoring.web_v3.readiness import manager_cases
from credit_monitoring.web_v3.state import commit, go


def filtered_cases(services, period, cutoff):
    cases = manager_cases(services, period, cutoff)
    selected = st.session_state.get("v3_risk_filter", "Needs attention")
    search = st.session_state.get("v3_risk_search", "").strip().casefold()
    return [
        c
        for c in cases
        if (
            selected == "All cases"
            or (c["attention"] if selected == "Needs attention" else c["state"] == "Reviewed")
        )
        and (not search or search in f"{c['name']} {c['borrower_id']} {c['reason']}".casefold())
    ]


def render_queue(services, period, cutoff) -> None:
    st.title("Risk manager")
    st.caption(
        "Prioritized borrower cases. Open a case to inspect findings and record your decision."
    )
    cases = manager_cases(services, period, cutoff)
    columns = st.columns(3)
    columns[0].metric("Cases needing attention", sum(c["attention"] for c in cases))
    columns[1].metric("Flagged borrowers", sum(bool(c["flags"]) for c in cases))
    columns[2].metric("Outstanding requests", sum(len(c["requests"]) for c in cases))
    st.radio(
        "Cases", ["Needs attention", "All cases", "Reviewed"], horizontal=True, key="v3_risk_filter"
    )
    st.text_input("Search risk cases", key="v3_risk_search", placeholder="Borrower, ID, or issue")
    filtered = filtered_cases(services, period, cutoff)
    st.session_state.v3_risk_order = [c["borrower_id"] for c in filtered]
    if not filtered:
        st.info("No cases match this queue. Flag or submit a borrower from the analyst workspace.")
    for case in filtered:
        with st.container(border=True):
            due = case["due"] if case["due"] != "9999-12-31" else "Not assigned"
            details, action = st.columns([4, 1])
            details.subheader(case["name"])
            details.write(f"**{case['severity']} · {case['state']}**")
            details.write(case["reason"])
            details.caption(
                f"{len(case['flags'])} open flags · "
                f"{len(case['requests'])} outstanding "
                f"requests · Due: {due}"
            )
            if action.button(
                "Open case",
                key=f"v3btn_case_{case['borrower_id']}",
                type="primary",
                width="stretch",
            ):
                go("Risk case", case["borrower_id"])


def render_case(services, period, cutoff) -> None:
    left, right = st.columns(2)
    if left.button("← Back to risk queue", key="v3btn_case_back"):
        go("Risk manager")
    cases = manager_cases(services, period, cutoff)
    bid = st.session_state.get("v3_borrower")
    case = next((c for c in cases if c["borrower_id"] == bid), None)
    order = st.session_state.get("v3_risk_order", [c["borrower_id"] for c in cases])
    eligible = {c["borrower_id"] for c in filtered_cases(services, period, cutoff)}
    remaining = [b for b in order if b in eligible and b != bid]
    if bid in order:
        pos = order.index(bid)
        remaining = [b for b in order[pos + 1 :] + order[:pos] if b in eligible and b != bid]
    if right.button("Next case →", key="v3btn_case_next", disabled=not remaining):
        go("Risk case", remaining[0])
    if not case:
        st.info(
            "This borrower has no case in the selected reporting scope. Return "
            "to the queue or adjust the dates."
        )
        return
    manager = services.manager
    st.title(case["name"])
    st.write(f"**{case['severity']} · {case['state']}**")
    st.write(case["reason"])
    st.caption(f"{bid} · Reporting scope through {period} · Information cutoff {cutoff}")
    submissions = [
        s
        for s in manager.repository.submissions(bid)
        if manager.assessment(s).period_end <= period
        and manager.assessment(s).information_cutoff <= cutoff
    ]
    if not submissions:
        st.info(
            "No analyst submission. Flags and saved calculations are inspectable; "
            "submit validated findings before manager sign-off."
        )
        if case["assessment"]:
            if st.button("Open analyst workspace", key="v3btn_case_analyst"):
                open_analyst(services, case["assessment"])
            render_covenant_table(case["assessment"], key="v3table_unsubmitted")
            with st.expander("Saved evidence"):
                render_verification(case["assessment"])
                render_evidence(case["assessment"])
        for flag in case["flags"]:
            st.write(f"**{flag['payload']['severity']}** · {flag['payload']['explanation']}")
        return
    lookup = {s["submission_id"]: s for s in submissions}
    key = f"v3_submission_{bid}"
    if st.session_state.get(key) not in lookup:
        st.session_state[key] = next(iter(lookup))
    sid = st.selectbox(
        "Submitted version",
        list(lookup),
        key=key,
        format_func=lambda s: (
            f"{manager.assessment(lookup[s]).period_end} · "
            f"{formatted_time(lookup[s]['created_at'])} "
            f"· {s}"
        ),
    )
    submission = lookup[sid]
    assessment = manager.assessment(submission)
    if st.button("Open analyst workspace", key="v3btn_case_analyst"):
        open_analyst(services, assessment)
    review = manager.current_review(submission, cutoff=cutoff)
    st.caption(
        f"Frozen submission · Assessment {assessment.assessment_run_id} · "
        f"Saved cutoff {assessment.information_cutoff}"
    )
    st.subheader("Analyst findings and material issues")
    st.write(submission["payload"]["text"])
    st.caption(f"Analyst: {submission['payload']['analyst'] or 'Unspecified'}")
    if submission["payload"]["triage"]:
        st.write("Breach triage: " + submission["payload"]["triage"])
    validation = submission["payload"]["validation"]["payload"]
    if validation["notes"]:
        st.write("Validation notes / exceptions: " + validation["notes"])
    for flag in submission["payload"]["flags"]:
        st.write(
            f"**{flag['payload']['severity']} · {flag['payload']['category']}** "
            f"— {flag['payload']['explanation']}"
        )
        st.caption(flag["payload"]["action"] or "No proposed action recorded.")
    render_covenant_table(assessment, key="v3table_manager_covenants")
    st.subheader("Current document readiness · separate from the frozen submission")
    items = services.checklists.load(bid, assessment.period_end)
    if items is None:
        st.info(
            "Requirements not configured. This is a current advisory status, "
            "not submitted evidence."
        )
    elif not items:
        st.caption("Current checklist: no documents required.")
    else:
        for item in checklist_states(items, bid, services.documents.inventory()):
            st.write(f"{item['document_type']} · {item['state']}")
    st.subheader("Requests and responses")
    render_requests(services, bid)
    st.subheader("Manager decision")
    state = manager.state(submission)
    latest = manager.current_review(submission)
    hidden_review = (latest.review_id if latest else None) != (review.review_id if review else None)
    blockers = []
    if state not in {"Pending review", "Reviewed"}:
        blockers.append(state)
    if hidden_review:
        blockers.append(
            "A newer AI review uses later information. Advance the information "
            "cutoff and inspect it."
        )
    for blocker in blockers:
        st.warning(blocker)
    previous = next(
        (n["payload"] for n in manager.repository.notes(bid) if n["submission_id"] == sid), {}
    )
    with st.form(f"v3form_decision_{sid}_{review.review_id if review else 'none'}"):
        reviewer = st.text_input(
            "Manager name (optional)", value=previous.get("manager", ""), key=f"v3_manager_{sid}"
        )
        comment = st.text_area(
            "Manager observations",
            value=previous.get("comment", ""),
            key=f"v3_manager_comment_{sid}",
        )
        recommendation = st.text_area(
            "Recommendation",
            value=previous.get("recommendation", ""),
            key=f"v3_manager_recommendation_{sid}",
        )
        disposition = st.selectbox(
            "Decision / next step",
            ["Continue monitoring", "Request remediation", "Resolve selected flags"],
            key=f"v3_disposition_{sid}",
        )
        submitted_ids = {f["flag_id"] for f in submission["payload"]["flags"]}
        resolvable = {
            f["flag_id"]: f for f in manager.active_flags(bid) if f["flag_id"] in submitted_ids
        }
        resolve = st.multiselect(
            "Flags to resolve",
            list(resolvable),
            key=f"v3_resolve_{sid}",
            format_func=lambda f: resolvable[f]["payload"]["explanation"],
        )
        save, finish = st.columns(2)
        draft = save.form_submit_button("Save manager notes")
        complete = finish.form_submit_button(
            "Complete manager review", type="primary", disabled=bool(blockers)
        )
        if draft or complete:
            commit(
                lambda: manager.record_note(
                    sid,
                    comment=comment,
                    recommendation=recommendation,
                    manager=reviewer,
                    reviewed=complete,
                    disposition=disposition,
                    resolve_ids=resolve if complete else [],
                    review_cutoff=cutoff,
                ),
                "Manager decision saved.",
            )
    render_new_request(services, submission, cutoff)
    with st.expander("Supporting AI analysis and evidence"):
        if review:
            render_agent_result(review)
        else:
            st.info("No AI analysis available at this cutoff. AI analysis is optional.")
        render_verification(assessment)
        render_evidence(assessment)
    with st.expander("Previous AI reviews and manager decisions"):
        for old in manager.portfolio.repository.review_history(assessment.assessment_run_id):
            if (
                old.snapshot.review_information_cutoff or old.snapshot.information_cutoff
            ) <= cutoff:
                st.caption(f"AI review {old.review_id} · {old.status}")
                st.write(old.recommendation.rationale)
        for note in manager.repository.notes(bid):
            st.caption(formatted_time(note["created_at"]))
            st.write(note["payload"]["comment"])
            st.write(note["payload"]["recommendation"])


def open_analyst(services, assessment) -> None:
    requests = services.manager.pending_requests(assessment.borrower_id)
    cutoff = max(
        [
            assessment.information_cutoff,
            *[date.fromisoformat(r["payload"]["review_cutoff"]) for r in requests],
        ]
    )
    st.session_state.v3_next_run = assessment.assessment_run_id
    st.session_state["_v3_route"] = {
        "v3_page": "Borrower",
        "v3_borrower": assessment.borrower_id,
        "v3_period": assessment.period_end.isoformat(),
        "v3_cutoff": cutoff,
        "v3_section": "Review and submit",
    }
    st.rerun()


def render_new_request(services, submission, cutoff) -> None:
    sid = submission["submission_id"]
    st.subheader("Follow-up actions")
    mode = st.radio(
        "Follow-up action",
        ["Request analyst follow-up", "Run supplementary AI analysis"],
        horizontal=True,
        key=f"v3_request_mode_{sid}",
    )
    direct = mode == "Run supplementary AI analysis"
    with st.form(f"v3form_new_request_{sid}_{direct}"):
        kind = (
            "context"
            if direct
            else st.selectbox(
                "Request type",
                ["context", "correction"],
                format_func=lambda k: (
                    "Additional context / credit review"
                    if k == "context"
                    else "Correct inputs / terms and resubmit"
                ),
                key=f"v3_request_kind_{sid}",
            )
        )
        question = st.text_input(
            "Question / work requested", key=f"v3_request_question_{sid}_{direct}"
        )
        owner = st.text_input("Assigned analyst (optional)", key=f"v3_request_owner_{sid}_{direct}")
        due = st.date_input(
            "Due date", date.today() + timedelta(days=7), key=f"v3_request_due_{sid}_{direct}"
        )
        with st.expander("Context, sources and review criteria"):
            context = st.text_area("Additional context", key=f"v3_request_context_{sid}_{direct}")
            source = st.text_input(
                "Source / reference (optional)", key=f"v3_request_source_{sid}_{direct}"
            )
            available = st.date_input(
                "Information available on (optional)",
                value=None,
                key=f"v3_request_available_{sid}_{direct}",
            )
            review_cutoff = st.date_input(
                "Review information cutoff", cutoff, key=f"v3_request_cutoff_{sid}_{direct}"
            )
            criteria = st.text_area(
                "Review criteria",
                "\n".join(DEFAULT_CRITERIA),
                key=f"v3_request_criteria_{sid}_{direct}",
            )
        if direct:
            st.caption(
                "Runs supporting, opposing and recommendation agents on saved calculations. "
                "Provider usage applies. The saved response still needs manager "
                "acceptance."
            )
        else:
            st.caption(
                "Saves work in the analyst queue. Context requests need supplementary "
                "AI analysis; corrections need recalculation, validation and resubmission."
            )
        if st.form_submit_button(
            "Run supplementary analysis" if direct else "Create analyst request",
            disabled=direct and not credentials(),
        ):

            def request():
                rid = services.manager.request_analysis(
                    sid,
                    kind=kind,
                    question=question,
                    context=context,
                    source=source,
                    available_at=available,
                    review_cutoff=review_cutoff,
                    owner=owner,
                    due=due,
                    criteria=tuple(c.strip() for c in criteria.splitlines() if c.strip()),
                )
                if direct:
                    with st.spinner("Running supplementary analysis…"):
                        services.manager.run_requested_review(rid)
                return rid

            commit(request, "Follow-up saved. Inspect its status in Requests and responses.")


def render_requests(services, bid, *, analyst=False) -> None:
    manager = services.manager
    requests = manager.repository.requests(bid)
    if not requests:
        st.caption("No follow-up requests for this borrower.")
    for request in requests:
        rid, item = request["request_id"], request["payload"]
        closed = request["state"] in {"accepted", "cancelled"}
        with st.expander(
            f"{item['question']} · {request['state'].replace('_', ' ')}", expanded=not closed
        ):
            st.caption(
                f"Assigned to {item['owner'] or 'Analyst'} · "
                f"Due {item['due'] or 'Not assigned'} "
                f"· {item['kind']} · Required cutoff {item['review_cutoff']}"
            )
            st.caption(
                f"Assessment {request['run_id']} · "
                f"Source {item['source'] or 'Unsourced assumption'}"
            )
            st.write(item["context"] or "No additional context.")
            if item.get("last_error"):
                st.warning(item["last_error"])
            if item.get("response"):
                st.write("**Response:** " + item["response"])
            if item.get("review_id"):
                with st.expander("Read supplementary AI analysis"):
                    render_agent_result(manager.portfolio.repository.get_review(item["review_id"]))
            if closed:
                if item.get("cancellation_reason"):
                    st.write(item["cancellation_reason"])
                continue
            if item["kind"] == "context" and request["state"] == "open":
                st.caption(
                    "Uses the saved assessment and additional context; provider usage applies."
                )
                if st.button(
                    "Run requested analysis",
                    key=f"v3btn_request_run_{rid}",
                    disabled=not credentials(),
                ):

                    def run():
                        with st.spinner("Running requested analysis…"):
                            return manager.run_requested_review(rid)

                    commit(run, "Requested analysis saved. Inspect the response before accepting.")
            if analyst:
                if item["kind"] == "correction":
                    if st.button(
                        "Revise inputs for this request", key=f"v3btn_request_revise_{rid}"
                    ):
                        original = manager.portfolio.repository.get_assessment(request["run_id"])
                        st.session_state["_v3_route"] = {
                            "v3_page": "Borrower",
                            "v3_borrower": bid,
                            "v3_period": original.period_end.isoformat(),
                            "v3_cutoff": date.fromisoformat(item["review_cutoff"]),
                            "v3_section": "Evidence",
                        }
                        st.rerun()
                with st.form(f"v3form_response_{rid}"):
                    chosen = None
                    if item["kind"] == "correction":
                        original = manager.portfolio.repository.get_assessment(request["run_id"])
                        choices = {
                            s["submission_id"]: s
                            for s in manager.repository.submissions(bid)
                            if s["created_at"] > request["created_at"]
                            and s["run_id"] != request["run_id"]
                            and manager.assessment(s).period_end == original.period_end
                        }
                        st.caption(
                            "Recalculate, validate and submit corrected findings before responding."
                        )
                        if choices:
                            chosen = st.selectbox(
                                "Corrected submission",
                                list(choices),
                                key=f"v3_response_submission_{rid}",
                            )
                    response = st.text_area(
                        "Response to manager",
                        value=item.get("response", ""),
                        key=f"v3_response_{rid}",
                    )
                    if st.form_submit_button("Submit response"):
                        commit(
                            lambda: manager.respond(rid, response=response, submission_id=chosen),
                            "Response saved for manager acceptance.",
                        )
            else:
                if st.button(
                    "Accept response",
                    key=f"v3btn_accept_{rid}",
                    disabled=request["state"] != "response_ready",
                ):
                    commit(lambda: manager.accept_response(rid), "Response accepted.")
                with st.form(f"v3form_cancel_{rid}"):
                    reason = st.text_input("Cancellation reason", key=f"v3_cancel_{rid}")
                    if st.form_submit_button("Cancel request"):
                        commit(
                            lambda: manager.cancel_request(rid, reason=reason), "Request cancelled."
                        )
