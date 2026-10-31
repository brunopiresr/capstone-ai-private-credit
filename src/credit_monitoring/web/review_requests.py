"""Shared request/response controls for the manager and analyst pages."""

import os

import streamlit as st

from credit_monitoring.application.manager_workflow import ManagerWorkflow


def run_action(callback, message: str) -> None:
    try:
        callback()
    except ValueError as error:
        st.warning(str(error))
    except Exception as error:
        st.error(f"Action failed ({type(error).__name__}). Saved records are retained.")
    else:
        st.toast(message)
        st.rerun()


def render_requests(manager: ManagerWorkflow, borrower_id: str, *, analyst: bool = False) -> None:
    requests = manager.repository.requests(borrower_id)
    if not requests:
        st.caption("No further-analysis requests for this borrower.")
    for request in requests:
        rid, item = request["request_id"], request["payload"]
        with st.expander(
            f"{item['question']} · {request['state'].replace('_', ' ')}",
            expanded=request["state"] not in {"accepted", "cancelled"},
        ):
            st.caption(f"Request {rid} · {item['kind']} · Assessment {request['run_id']}")
            st.write(item["context"] or "No additional context supplied.")
            st.caption(
                f"Source: {item['source'] or 'Unsourced assumption'} · "
                f"Available on: {item['available_at'] or 'Unknown'} · "
                f"Review cutoff: {item['review_cutoff']}"
            )
            st.caption(
                f"Assigned to {item['owner'] or 'Analyst'} · Due {item['due'] or 'Not specified'}"
            )
            if item.get("last_error"):
                st.warning(item["last_error"])
            if item.get("response"):
                st.markdown("**Analyst / review response**")
                st.write(item["response"])
            if item.get("review_id"):
                st.caption(f"Supplementary review {item['review_id']}")
            if item.get("fulfillment_submission_id"):
                st.caption(f"Corrected analyst submission {item['fulfillment_submission_id']}")
            if request["state"] in {"accepted", "cancelled"}:
                if item.get("cancellation_reason"):
                    st.caption(f"Cancelled: {item['cancellation_reason']}")
                continue
            if item["kind"] == "context" and request["state"] == "open":
                st.caption(
                    "Runs the three risk agents, then generates follow-up questions. "
                    "Provider usage applies."
                )
                if st.button(
                    "Run requested review",
                    key=f"request_run_{rid}",
                    disabled=not bool(os.getenv("OPENAI_API_KEY", "").strip()),
                ):

                    def run_review():
                        with st.status("Running risk agents and generating follow-up questions…"):
                            review = manager.run_requested_review(rid)
                        if review.status != "complete":
                            st.session_state._request_notice = (
                                "The review was saved but is incomplete. Retry explicitly."
                            )

                    run_action(run_review, "Requested review saved.")
            if analyst:
                with st.form(f"request_response_{rid}"):
                    chosen = None
                    if item["kind"] == "correction":
                        st.info(
                            "Recalculate, validate and submit the corrected borrower-period "
                            "before responding."
                        )
                        choices = [
                            s
                            for s in manager.repository.submissions(borrower_id)
                            if s["created_at"] > request["created_at"]
                            and s["run_id"] != request["run_id"]
                        ]
                        lookup = {s["submission_id"]: s for s in choices}
                        chosen = (
                            st.selectbox(
                                "Corrected analyst submission",
                                list(lookup),
                                format_func=lambda sid: f"{lookup[sid]['created_at']} · {sid}",
                                key=f"request_submission_{rid}",
                            )
                            if choices
                            else None
                        )
                    response = st.text_area(
                        "Response to manager",
                        value=item.get("response", ""),
                        key=f"request_response_text_{rid}",
                    )
                    if st.form_submit_button("Submit response"):
                        run_action(
                            lambda: manager.respond(rid, response=response, submission_id=chosen),
                            "Response saved for manager acceptance.",
                        )
            else:
                if st.button(
                    "Accept response",
                    key=f"request_accept_{rid}",
                    disabled=request["state"] != "response_ready",
                ):
                    run_action(lambda: manager.accept_response(rid), "Response accepted.")
                with st.form(f"request_cancel_{rid}"):
                    reason = st.text_input(
                        "Cancellation reason", key=f"request_cancel_reason_{rid}"
                    )
                    if st.form_submit_button("Cancel request"):
                        run_action(
                            lambda: manager.cancel_request(rid, reason=reason), "Request cancelled."
                        )


def render_manager_feedback(manager: ManagerWorkflow, borrower_id: str) -> None:
    notes = manager.repository.notes(borrower_id)
    if notes:
        st.subheader("Manager feedback")
    for note in notes[:8]:
        item = note["payload"]
        with st.container(border=True):
            st.caption(
                f"{item['manager'] or 'Risk manager'} · {note['created_at']} · "
                f"{item['state']} · Assessment {note['run_id']}"
            )
            if item["comment"]:
                st.write(item["comment"])
            if item["recommendation"]:
                st.write(item["recommendation"])
    st.subheader("Further-analysis requests")
    render_requests(manager, borrower_id, analyst=True)
