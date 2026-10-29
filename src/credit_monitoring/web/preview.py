"""Streamlit POC: connected portfolio, with the other workflows still in UX preview."""

from collections.abc import Callable
from copy import deepcopy
from datetime import date, timedelta
from html import escape
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from credit_monitoring.web.preview_data import (
    active_flags,
    add_flag,
    board_items,
    complete_request,
    finalize_report,
    initial_preview,
    log_event,
    request_analysis,
    sample_credit_snapshot,
    sample_reply,
    simulate_assessment,
    simulate_review,
    timestamp,
)
from credit_monitoring.web.preview_style import render_preview_style

PAGES = ["Portfolio", "Borrower analysis", "Documents & data", "Risk review", "Board report"]
PERIOD = "Q3 2026"
DEFAULT_SUMMARY = (
    "The portfolio requires targeted attention to covenant breaches, narrowing headroom "
    "and incomplete reporting. Prioritize remediation plans for breached borrowers and "
    "resolve conflicting source data before accepting compliance conclusions."
)


def data() -> dict:
    return st.session_state.preview_data


def flash(message: str) -> None:
    st.session_state._preview_flash = message


def navigate(page: str, borrower_id: str | None = None) -> None:
    st.session_state._preview_next_page = page
    if borrower_id:
        st.session_state.preview_selected_borrower = borrower_id
    st.rerun()


def reset_preview() -> None:
    for key in list(st.session_state):
        if key.startswith(("preview_", "_preview_")):
            del st.session_state[key]


def sync_borrower(widget_key: str) -> None:
    st.session_state.preview_selected_borrower = st.session_state[widget_key]
    if widget_key == "preview_risk_borrower":
        # Clear an older queue highlight when the top selector changes the borrower.
        st.session_state.preview_risk_queue_revision = (
            st.session_state.get("preview_risk_queue_revision", 0) + 1
        )


def select_risk_queue_row(widget_key: str, borrower_ids: tuple[str, ...]) -> None:
    """Handle ordinary cell clicks as well as the table's row-selector clicks."""
    selection = st.session_state[widget_key]["selection"]
    rows = tuple(selection["rows"])
    cells = tuple(tuple(cell) for cell in selection.get("cells", []))
    previous = st.session_state.get("_preview_risk_queue_selection", {})
    if previous.get("key") != widget_key:
        previous = {}
    st.session_state._preview_risk_queue_selection = {
        "key": widget_key,
        "rows": rows,
        "cells": cells,
    }
    # Streamlit retains the other selection type. Use the selection that changed,
    # so an old checked row cannot override a new cell click (or vice versa).
    if cells and cells != previous.get("cells", ()):
        row = cells[0][0]
    elif rows and rows != previous.get("rows", ()):
        row = rows[0]
    else:
        return
    if 0 <= row < len(borrower_ids):
        borrower_id = borrower_ids[row]
        st.session_state.preview_selected_borrower = borrower_id
        st.session_state.preview_risk_borrower = borrower_id


def borrower_picker(key: str, label: str = "Borrower") -> dict:
    borrowers = data()["borrowers"]
    borrower_ids = list(borrowers)
    current = st.session_state.preview_selected_borrower
    # Widget keys are page-specific; the selected borrower is kept separately.
    if key not in st.session_state or st.session_state[key] != current:
        st.session_state[key] = current
    borrower_id = st.selectbox(
        label,
        borrower_ids,
        format_func=lambda bid: borrowers[bid]["name"],
        key=key,
        on_change=sync_borrower,
        args=(key,),
    )
    return borrowers[borrower_id]


def chip(label: str, tone: str = "grey") -> str:
    return f'<span class="preview-chip chip-{tone}">{escape(label)}</span>'


def status_chip(status: str) -> str:
    tone = {"Compliant": "green", "Breach": "red", "Incomplete": "amber"}.get(status, "grey")
    return chip(status, tone)


def number(value: float | None, suffix: str = "x") -> str:
    return "—" if value is None else f"{value:.2f}{suffix}"


def page_header(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(f'<div class="preview-eyebrow">{escape(eyebrow)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(
        f'<div class="preview-subtitle">{escape(subtitle)}</div>',
        unsafe_allow_html=True,
    )


def notice(text: str) -> None:
    st.markdown(f'<div class="preview-notice">{escape(text)}</div>', unsafe_allow_html=True)


def preview_table(
    rows: list[dict],
    *,
    key: str | None = None,
    selectable: bool = False,
    on_select: Callable[[], None] | None = None,
    selection_mode: str | list[str] = "single-row",
):
    options = {}
    if selectable:
        options = {"on_select": on_select or "rerun", "selection_mode": selection_mode, "key": key}
    return st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        row_height=43,
        **options,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="preview-brand"><div class="preview-mark">◈</div>'
            "<div><b>Credit Monitor</b><small>PRIVATE CREDIT WORKSPACE</small></div></div>",
            unsafe_allow_html=True,
        )
        st.caption("NAVIGATION")
        st.radio("Navigation", PAGES, key="preview_page", label_visibility="collapsed")
        st.divider()
        if st.session_state.preview_page == "Portfolio":
            st.caption("CONNECTED PORTFOLIO")
            st.caption("Choose reporting dates on the Portfolio page. Runs are saved locally.")
        else:
            st.caption("SAMPLE REPORTING PERIOD")
            st.selectbox("Reporting period", [PERIOD], label_visibility="collapsed")
            st.caption("Period ending 30 September 2026")
        with st.container(border=True):
            st.markdown("**Connecting one step at a time.**")
            st.caption(
                "Portfolio uses the services and agents. Borrower analysis, risk review, "
                "documents and board reporting remain sample screens."
            )
        st.button(
            "Reset sample screens", key="preview_reset", on_click=reset_preview, width="stretch"
        )
        st.caption("Resetting sample screens keeps saved portfolio assessments and agent reviews.")


def render_portfolio() -> None:
    from credit_monitoring.web.portfolio import render_portfolio_page

    render_portfolio_page()


def render_calculations(borrower: dict) -> None:
    st.subheader("Covenant calculations")
    st.caption(
        "Illustrative inputs and results for layout testing. No calculation service is running."
    )
    if borrower["status"] == "Not assessed":
        st.info("No assessment is available. Use Run assessment to try creating a sample run.")
    test_active = borrower["status"] not in {"Waived", "Not tested", "Not assessed"}
    headroom = (
        borrower["limit"] - borrower["leverage"]
        if test_active and borrower["leverage"] is not None
        else None
    )
    preview_table(
        [
            {
                "Covenant": "Total leverage",
                "Actual": number(borrower["leverage"]),
                "Threshold": f"≤ {number(borrower['limit'])}" if borrower["limit"] else "—",
                "Headroom": number(headroom),
                "Compliance": borrower["status"],
            }
        ]
    )
    left, right = st.columns([1.4, 1])
    with left:
        with st.container(border=True):
            st.subheader("Input trace")
            preview_table(
                [
                    {
                        "Input": "Total debt",
                        "Sample value": f"€{borrower['leverage'] * 20:.1f}m"
                        if borrower["leverage"]
                        else "Unavailable",
                        "Source": "Quarterly financial statements · p. 12",
                    },
                    {
                        "Input": "Adjusted EBITDA",
                        "Sample value": "€20.0m" if borrower["leverage"] else "Unavailable",
                        "Source": "Compliance certificate · p. 3",
                    },
                    {
                        "Input": "Maximum leverage",
                        "Sample value": number(borrower["limit"]),
                        "Source": "Credit agreement · §7.11",
                    },
                ]
            )
            st.code("Total leverage = total debt / adjusted EBITDA", language=None)
    with right:
        with st.container(border=True):
            st.subheader("Verification & exceptions")
            if borrower["status"] == "Incomplete":
                st.warning("Debt differs between the financial package and compliance certificate.")
                st.caption("The sample assessment abstains until the discrepancy is resolved.")
            elif borrower["status"] == "Not assessed":
                st.info("Verification has not been performed.")
            else:
                st.markdown(
                    "✓ Input references shown  \n✓ Applied terms shown  \n✓ Sample output available"
                )
                st.caption(
                    "These checks illustrate the UI; they are not live verification results."
                )
            st.markdown("**Contract basis**")
            st.caption("Reporting quarter · EUR millions · agreement-specific definitions")
    with st.expander("Source excerpt · Credit agreement, section 7.11"):
        st.markdown(
            f"> Illustrative excerpt: the borrower shall maintain total leverage at or below "
            f"{number(borrower['limit'])} for the applicable test period."
        )
        st.caption("Sample source text for UX testing; no real legal document has been retrieved.")


def render_credit_snapshot(borrower: dict, *, show_heading: bool = True) -> None:
    if show_heading:
        st.header("Credit analysis snapshot")
    st.caption(
        f"Review v{borrower['review_version']} · Assessment v{borrower['version']}"
        " · Illustrative agent arguments"
    )
    snapshot = sample_credit_snapshot(borrower)
    if not snapshot:
        st.info("Agent arguments are not available until a borrower assessment is available.")
        return
    for column, role in zip(st.columns(3), ("bullish", "bearish", "recommendation"), strict=True):
        agent = snapshot[role]
        with column:
            with st.container(border=True):
                st.markdown(chip(agent["label"], agent["tone"]), unsafe_allow_html=True)
                st.subheader(agent["name"])
                st.markdown(f"**{agent['thesis']}**")
                st.markdown("\n".join(f"- {argument}" for argument in agent["arguments"]))
                st.caption(agent["basis"])
    if borrower["contexts"]:
        st.markdown("**Latest supplementary context**")
        st.write(borrower["contexts"][0]["context"] or "No extra context.")
        st.caption("Context recorded for this sample review; the arguments are illustrative.")


def render_credit_analysis(borrower: dict) -> None:
    heading, action = st.columns([2, 1])
    heading.header("Credit analysis snapshot")
    if action.button("Run sample bull / bear review", key="preview_run_credit", width="stretch"):
        simulate_review(data(), borrower["id"])
        flash("Sample review created. No agents were called.")
        st.rerun()
    render_credit_snapshot(borrower, show_heading=False)
    with st.form(f"preview_context_form_{borrower['id']}"):
        context = st.text_area(
            "Add context for another review",
            placeholder="e.g. Management expects a delayed "
            "customer payment to settle next month. What would change the downside view?",
            key=f"preview_context_{borrower['id']}",
        )
        if st.form_submit_button("Run review with this context"):
            if not context.strip():
                st.warning("Add the question or context to include in the sample review.")
            else:
                simulate_review(data(), borrower["id"], context.strip())
                flash("Context saved to a new sample review. Prior versions remain in history.")
                st.rerun()
    for item in borrower["contexts"][:3]:
        with st.expander(f"Review v{item['version']} · Additional context"):
            st.write(item["context"] or "No additional context supplied.")
            st.caption(
                f"{item['at']} · Context saved, sample analysis retained; no model execution."
            )


def send_chat(borrower: dict, question: str) -> None:
    chat_key = f"{borrower['id']}:{borrower['version']}"
    messages = data()["chats"].setdefault(chat_key, [])
    messages.extend(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": sample_reply(data(), borrower["id"], question)},
        ]
    )


def render_chat(borrower: dict, *, expanded: bool = False) -> None:
    context = "expanded" if expanded else "panel"
    chat_key = f"{borrower['id']}:{borrower['version']}"
    messages = data()["chats"].setdefault(chat_key, [])
    st.caption(f"{borrower['name']} · Assessment v{borrower['version']}")
    st.caption("Scripted sample replies · no AI connection")
    with st.container(height=430 if not expanded else 480):
        if not messages:
            st.markdown("**A second pair of eyes.**")
            st.write("Ask about a covenant, explore a trend, or prepare an observation.")
            st.caption("Your borrower analysis stays beside the conversation.")
        for message in messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
    quick = st.button(
        "Explain the key concern", key=f"preview_chat_quick_{context}", width="stretch"
    )
    question = st.chat_input(
        "Ask about this borrower…",
        key=f"preview_chat_input_{context}_{chat_key}",
    )
    if quick or question:
        send_chat(borrower, question if question else "Explain the key concern")
        st.rerun()


def close_expanded_chat() -> None:
    st.session_state.preview_chat_expanded = False


@st.dialog("Credit assistant", width="large", on_dismiss=close_expanded_chat)
def expanded_chat(borrower_id: str) -> None:
    render_chat(data()["borrowers"][borrower_id], expanded=True)
    if st.button("Back to analysis", on_click=close_expanded_chat):
        st.rerun()


def render_requests(borrower: dict) -> None:
    requests = [item for item in data()["requests"] if item["borrower_id"] == borrower["id"]]
    for request in requests:
        with st.expander(
            f"{request['id']} · {request['status']} · {request['question']}", expanded=True
        ):
            st.write(request["context"] or "No additional context.")
            st.caption(f"Assigned to {request['owner']} · Due {request['due']}")
            if request["status"] == "Open":
                changed = (
                    borrower["version"] > request["version"]
                    or borrower["review_version"] > request["review_version"]
                )
                with st.form(f"preview_response_form_{request['id']}"):
                    response = st.text_area(
                        "Response to manager", key=f"preview_response_{request['id']}"
                    )
                    st.caption(
                        "Create a new assessment or credit review before submitting your response."
                    )
                    if st.form_submit_button("Submit response", disabled=not changed):
                        if not response.strip():
                            st.warning("Add a short response explaining what you reviewed.")
                        else:
                            complete_request(data(), request["id"], response.strip())
                            flash("Response returned to the risk manager.")
                            st.rerun()
            elif request["response"]:
                st.markdown(f"**Analyst response**  \n{request['response']}")


def render_analyst_handoff(borrower: dict) -> None:
    render_requests(borrower)
    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Validate & prepare your handoff")
        st.caption("Record what you checked. The manager will see this assessment version.")
        with st.form(f"preview_validation_form_{borrower['id']}_{borrower['version']}"):
            checked_inputs = st.checkbox(
                "I checked the financial inputs and source references",
                value=borrower["validated"],
                key=f"preview_check_inputs_{borrower['id']}_{borrower['version']}",
            )
            checked_terms = st.checkbox(
                "I checked the applied terms and calculations",
                value=borrower["validated"],
                key=f"preview_check_terms_{borrower['id']}_{borrower['version']}",
            )
            checked_analysis = st.checkbox(
                "I reviewed the analysis and documented any exceptions",
                value=borrower["validated"],
                key=f"preview_check_analysis_{borrower['id']}_{borrower['version']}",
            )
            note = st.text_area(
                "Validation notes / exceptions",
                value=borrower["validation_note"],
                key=f"preview_validation_note_{borrower['id']}_{borrower['version']}",
                placeholder="What did you verify? What remains uncertain?",
            )
            if st.form_submit_button("Mark validated"):
                if borrower["status"] == "Not assessed":
                    st.warning("This borrower has no sample calculation results to validate.")
                elif not all((checked_inputs, checked_terms, checked_analysis)):
                    st.warning(
                        "Complete the three review checks before marking this version validated."
                    )
                elif borrower["status"] == "Incomplete" and not note.strip():
                    st.warning("Document the data exception before validating with exceptions.")
                else:
                    borrower["validated"] = True
                    borrower["validation_note"] = note.strip()
                    log_event(data(), borrower["id"], "Analyst validation recorded", note.strip())
                    flash(
                        "Assessment marked validated"
                        + (" with exceptions." if borrower["status"] == "Incomplete" else ".")
                    )
                    st.rerun()
    with right:
        st.subheader("Flag for risk review")
        st.caption("A flag explains why this borrower needs attention.")
        with st.form(f"preview_flag_form_{borrower['id']}", clear_on_submit=True):
            severity = st.selectbox("Severity", ["High", "Critical", "Medium", "Low"])
            category = st.selectbox(
                "Category",
                ["Covenant breach", "Deterioration", "Low headroom", "Data quality", "Other"],
            )
            explanation = st.text_area(
                "Short explanation", placeholder="What should the manager know?"
            )
            proposed_action = st.text_input(
                "Proposed action", placeholder="e.g. Obtain a liquidity update"
            )
            if st.form_submit_button("Add flag", type="primary"):
                if not explanation.strip():
                    st.warning("Add a short explanation for the flag.")
                else:
                    add_flag(
                        data(),
                        borrower["id"],
                        severity,
                        category,
                        explanation.strip(),
                        proposed_action.strip(),
                    )
                    flash("Flag added to this borrower.")
                    st.rerun()
    st.subheader("Analyst report")
    with st.form(f"preview_analyst_report_form_{borrower['id']}_{borrower['version']}"):
        report = st.text_area(
            "Observations and proposed recommendation",
            value=borrower["analyst_report"],
            height=150,
            key=f"preview_analyst_report_{borrower['id']}_{borrower['version']}",
        )
        col1, col2 = st.columns(2)
        save = col1.form_submit_button("Save draft", width="stretch")
        submit = col2.form_submit_button("Send to risk manager", type="primary", width="stretch")
        if save or submit:
            if not report.strip():
                st.warning("Add your observations before saving or submitting.")
            elif submit and not borrower["validated"]:
                st.warning(
                    "Validate this assessment version before sending it to the risk manager."
                )
            elif (
                submit
                and borrower["status"] == "Breach"
                and not active_flags(data(), borrower["id"])
            ):
                st.warning("Add a flag explaining the breach before submitting.")
            else:
                borrower["analyst_report"] = report.strip()
                if submit:
                    borrower["submitted"] = True
                    for flag in active_flags(data(), borrower["id"]):
                        flag["status"] = "Pending review"
                    log_event(data(), borrower["id"], "Analyst report submitted", report.strip())
                flash(
                    "Report sent to risk review."
                    if submit
                    else "Analyst draft saved in this preview."
                )
                st.rerun()
    for flag in active_flags(data(), borrower["id"]):
        with st.container(border=True):
            st.markdown(
                chip(flag["severity"], "red" if flag["severity"] == "Critical" else "amber")
                + chip(flag["status"])
                + f" **{escape(flag['category'])}**",
                unsafe_allow_html=True,
            )
            st.write(flag["explanation"])
            st.caption(flag["action"] or "No proposed action recorded.")
    for comment in data()["comments"]:
        if comment["borrower_id"] == borrower["id"]:
            st.info(f"Risk manager · {comment['at']}\n\n{comment['text']}")


def render_history(borrower: dict) -> None:
    st.subheader("Assessment & review history")
    rows = [
        {
            "Version": f"Assessment v{borrower['version']}",
            "State": "Current",
            "Compliance": borrower["status"],
            "Reason": "Active sample snapshot",
        }
    ]
    rows.extend(
        {
            "Version": f"Assessment v{item['version']}",
            "State": "Previous",
            "Compliance": item["status"],
            "Reason": "Preserved when the sample was rerun",
        }
        for item in borrower["history"]
        if item["version"]
    )
    preview_table(rows)
    st.caption("Sample recalculations preserve the illustrative ratios and compliance state.")
    for item in borrower["contexts"]:
        with st.expander(f"Credit review v{item['version']} · {item['at']}"):
            st.write(item["context"] or "No supplemental context.")
    events = [item for item in data()["events"] if item["borrower_id"] == borrower["id"]]
    if not events:
        st.caption("Your preview actions will appear here.")
    for event in events:
        st.markdown(f"**{event['title']}**  \n{event['detail']}")
        st.caption(event["at"])


def render_borrower_analysis() -> None:
    borrower = borrower_picker("preview_analysis_borrower")
    page_header(
        f"Credit analyst / {borrower['id']}",
        borrower["name"],
        f"{borrower['sector']} · {borrower['period_end']} · Analyst: {borrower['analyst']}",
    )
    state_label = "Submitted" if borrower["submitted"] else "Analyst draft"
    st.markdown(
        status_chip(borrower["status"])
        + chip(state_label)
        + chip(f"Assessment v{borrower['version']}")
        + (
            chip("Validated", "green")
            if borrower["validated"]
            else chip("Needs validation", "amber")
        ),
        unsafe_allow_html=True,
    )
    toolbar = st.columns([1.2, 1, 1.2, 1])
    with toolbar[0]:
        if st.button(
            "Run assessment" if not borrower["version"] else "Recalculate",
            type="primary",
            key="preview_recalculate",
            width="stretch",
        ):
            simulate_assessment(data(), borrower["id"], "Requested from the borrower workspace.")
            flash("New sample version created; figures are unchanged and need validation.")
            st.rerun()
    with toolbar[1]:
        if st.button("Source documents", width="stretch"):
            navigate("Documents & data", borrower["id"])
    with toolbar[2]:
        st.date_input(
            "Information cutoff",
            date(2026, 10, 28),
            key="preview_cutoff",
            label_visibility="collapsed",
            min_value=date(2026, 9, 30),
        )
    show_chat = toolbar[3].toggle("Assistant", value=True, key="preview_show_chat")
    st.caption("Sample versioning only. Buttons do not run calculations, extraction or AI models.")
    if borrower["needs_review"]:
        st.warning(
            "Source documents changed in this preview. Reassess and validate before resubmitting."
        )
    columns = st.columns(3)
    columns[0].metric("Total leverage", number(borrower["leverage"]))
    columns[1].metric("Maximum leverage", number(borrower["limit"]))
    columns[2].metric("Interest coverage", number(borrower["coverage"]))
    main, assistant = st.columns([3, 1.15]) if show_chat else (st.container(), None)
    with main:
        overview, calculations, credit, handoff, history = st.tabs(
            [
                "Overview",
                "Calculations",
                "Credit analysis",
                "Analyst handoff",
                "History",
            ]
        )
        with overview:
            st.subheader("The current credit picture")
            st.write(borrower["summary"])
            render_credit_snapshot(borrower)
            if borrower["previous"] is not None and borrower["leverage"] is not None:
                st.caption("Total leverage · illustrative quarterly trend")
                st.line_chart(
                    pd.DataFrame(
                        {
                            "Quarter": ["Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026"],
                            "Leverage": [
                                borrower["previous"] * 0.94,
                                borrower["previous"] * 0.98,
                                borrower["previous"],
                                borrower["leverage"],
                            ],
                        }
                    ).set_index("Quarter"),
                    height=210,
                    color="#426c49",
                )
            else:
                st.info("A comparable sample trend is not available for this borrower.")
            flags = active_flags(data(), borrower["id"])
            st.subheader("Items requiring attention")
            if flags:
                for flag in flags:
                    st.markdown(f"**{flag['category']}**  \n{flag['explanation']}")
                    st.caption(f"{flag['severity']} priority · {flag['status']}")
            else:
                st.caption(
                    "No open analyst flags. Use Analyst handoff to add an observation or flag."
                )
            open_requests = [
                r
                for r in data()["requests"]
                if r["borrower_id"] == borrower["id"] and r["status"] == "Open"
            ]
            if open_requests:
                st.warning(
                    f"{len(open_requests)} manager request(s) await your response"
                    " in Analyst handoff."
                )
        with calculations:
            render_calculations(borrower)
        with credit:
            render_credit_analysis(borrower)
        with handoff:
            render_analyst_handoff(borrower)
        with history:
            render_history(borrower)
    if assistant is not None:
        with assistant:
            with st.container(border=True):
                title_col, expand_col = st.columns([2, 1])
                title_col.subheader("Credit assistant")
                if expand_col.button("Expand", key="preview_expand_chat", width="stretch"):
                    st.session_state.preview_chat_expanded = True
                render_chat(borrower)
        if st.session_state.get("preview_chat_expanded", False):
            expanded_chat(borrower["id"])
    else:
        st.session_state.preview_chat_expanded = False


def simulate_document_operation(kind: str, borrower_id: str, selected_ids: list[str]) -> None:
    documents = [doc for doc in data()["documents"] if doc["id"] in selected_ids]
    outcomes = []
    with st.status(f"Simulating {kind.lower()}…", expanded=True) as status:
        progress = st.progress(0)
        for index, document in enumerate(documents, 1):
            if kind == "Fetch":
                if document["status"] == "Not fetched":
                    document["status"] = "Ready to process"
                outcome = "Sample source available"
            elif document["status"] == "Not fetched":
                outcome = "Skipped · fetch the document first"
            else:
                document["status"] = "Processed"
                data()["borrowers"][document["borrower_id"]]["needs_review"] = True
                outcome = "Sample extraction complete"
            outcomes.append({"Document": document["id"], "Outcome": outcome})
            st.write(f"{document['title']} — {outcome}")
            progress.progress(index / len(documents))
        status.update(label=f"{kind} simulation finished", state="complete")
    operation = {
        "Operation": kind,
        "Borrower": data()["borrowers"][borrower_id]["name"],
        "Items": len(documents),
        "Status": "Simulated",
        "Time": timestamp(),
        "outcomes": outcomes,
    }
    data()["operations"].insert(0, operation)
    log_event(data(), borrower_id, f"{kind} simulation", f"{len(documents)} document(s)")


def render_documents() -> None:
    page_header(
        "Credit analyst / Sources",
        "Documents & data",
        "Bring in evidence, inspect processing, and keep the working data up to date.",
    )
    borrower = borrower_picker("preview_documents_borrower")
    notice(
        "Preview controls only. No URLs are fetched, no models are called, "
        "and no files or databases are changed."
    )
    documents = [doc for doc in data()["documents"] if doc["borrower_id"] == borrower["id"]]
    metrics = st.columns(3)
    metrics[0].metric("Registered documents", len(documents))
    metrics[1].metric("Processed", sum(d["status"] == "Processed" for d in documents))
    metrics[2].metric("Need attention", sum(d["status"] != "Processed" for d in documents))
    st.subheader("Source inventory")
    preview_table(
        [
            {
                "Document": doc["title"],
                "ID": doc["id"],
                "Type": doc["type"],
                "Date": doc["date"],
                "Status": doc["status"],
            }
            for doc in documents
        ]
    )
    doc_lookup = {doc["id"]: doc for doc in documents}
    selected = st.multiselect(
        "Select documents to work with",
        list(doc_lookup),
        default=list(doc_lookup),
        format_func=lambda doc_id: doc_lookup[doc_id]["title"],
        key=f"preview_document_selection_{borrower['id']}",
    )
    fetch, process, reprocess = st.columns(3)
    kind = None
    if fetch.button("Fetch selected", disabled=not selected, width="stretch"):
        kind = "Fetch"
    if process.button("Process selected", type="primary", disabled=not selected, width="stretch"):
        kind = "Process"
    if reprocess.button("Reprocess selected", disabled=not selected, width="stretch"):
        kind = "Reprocess"
    if kind:
        simulate_document_operation(kind, borrower["id"], selected)
        flash(f"{kind} simulation complete. Inspect operation history for item outcomes.")
        st.rerun()
    register, maintenance = st.tabs(["Register a document", "Rebuild indexes & databases"])
    with register:
        with st.form("preview_document_register", clear_on_submit=True):
            st.caption(f"New source will be linked to {borrower['name']}.")
            title = st.text_input("Document title", placeholder="e.g. Q3 management reporting")
            url = st.text_input(
                "Source URL", placeholder="https://example.com/financial-report.html"
            )
            left, right = st.columns(2)
            kind = left.selectbox(
                "Document type",
                ["Financial statements", "Credit agreement", "Compliance certificate", "Other"],
            )
            document_date = right.date_input("Document date", date(2026, 9, 30))
            if st.form_submit_button("Register document", type="primary"):
                parsed = urlparse(url.strip())
                if not title.strip() or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    st.warning("Add a document title and a complete HTTP or HTTPS source URL.")
                elif any(
                    doc["url"] == url.strip() and doc["borrower_id"] == borrower["id"]
                    for doc in data()["documents"]
                ):
                    st.warning("This source is already registered for the borrower.")
                else:
                    data()["documents"].append(
                        {
                            "id": f"{borrower['id']}-NEW-{len(data()['documents']) + 1}",
                            "borrower_id": borrower["id"],
                            "title": title.strip(),
                            "url": url.strip(),
                            "type": kind,
                            "date": document_date.strftime("%d %b %Y"),
                            "status": "Not fetched",
                        }
                    )
                    flash("Document registered in sample data. You can now simulate fetching it.")
                    st.rerun()
    with maintenance:
        with st.container(border=True):
            st.subheader("Rebuild working data")
            st.caption(
                "Try the heavy-operation controls. This preview never changes your working files."
            )
            target = st.selectbox(
                "Rebuild target",
                [
                    "Retrieval index",
                    "Financial database",
                    "Extraction database",
                    "Analytics database",
                ],
            )
            scope = st.selectbox("Scope", ["Selected borrower", "All borrowers"])
            st.markdown("**What this would do**")
            descriptions = {
                "Retrieval index": "Regenerate searchable chunks from available source text.",
                "Financial database": (
                    "Reload known financial source files into a fresh working database."
                ),
                "Extraction database": (
                    "Restore extracted records or reprocess the selected source documents."
                ),
                "Analytics database": (
                    "Restore saved assessment results or rerun selected assessments."
                ),
            }
            st.write(descriptions[target])
            st.caption(
                "In the connected version, a local backup will preserve the previous working data."
            )
            if st.button("Simulate rebuild", key="preview_rebuild", type="primary"):
                with st.status(f"Simulating {target.lower()} rebuild…", expanded=True) as status:
                    st.write("1. Inspect sample sources")
                    st.write("2. Prepare sample replacement")
                    st.write("3. Check sample output")
                    st.progress(1.0)
                    status.update(label="Rebuild simulation complete", state="complete")
                data()["operations"].insert(
                    0,
                    {
                        "Operation": f"Rebuild {target.lower()}",
                        "Borrower": borrower["name"]
                        if scope == "Selected borrower"
                        else "All borrowers",
                        "Items": 1,
                        "Status": "Simulated",
                        "Time": timestamp(),
                        "outcomes": [],
                    },
                )
                flash("Rebuild simulated. No files or databases were modified.")
                st.rerun()
    with st.expander("Inspect sample extracted facts & source metadata"):
        document_id = st.selectbox(
            "Source document",
            list(doc_lookup),
            format_func=lambda doc_id: doc_lookup[doc_id]["title"],
            key=f"preview_inspect_document_{borrower['id']}",
        )
        doc = doc_lookup[document_id]
        st.code(doc["url"], language=None)
        if doc["status"] == "Processed":
            st.write(f"Sample extracted covenant: total leverage ≤ {number(borrower['limit'])}.")
            st.caption("Example fact for layout testing, not an extraction from this URL.")
        else:
            st.info("No complete sample extraction is available for this source.")
    st.subheader("Operation history")
    if not data()["operations"]:
        st.caption("Run a simulation to inspect processing outcomes here.")
    else:
        preview_table(
            [
                {k: v for k, v in operation.items() if k != "outcomes"}
                for operation in data()["operations"]
            ]
        )
        latest = data()["operations"][0]
        if latest["outcomes"]:
            with st.expander("Latest operation · document outcomes", expanded=True):
                preview_table(latest["outcomes"])


def render_manager_detail(borrower: dict) -> None:
    st.divider()
    title, action = st.columns([3, 1])
    title.subheader(borrower["name"])
    if action.button("Open full analysis →", width="stretch"):
        navigate("Borrower analysis", borrower["id"])
    st.markdown(
        status_chip(borrower["status"])
        + chip(f"Assessment v{borrower['version']}")
        + chip("Analyst submitted" if borrower["submitted"] else "Analyst draft"),
        unsafe_allow_html=True,
    )
    st.caption(
        f"{borrower['period']} · Credit review v{borrower['review_version']}"
        f" · {borrower['analyst']}"
    )
    render_credit_snapshot(borrower)
    left, right = st.columns([1.15, 1])
    with left:
        with st.container(border=True):
            st.subheader("Analyst handoff")
            st.write(borrower["analyst_report"])
            if borrower["validation_note"]:
                st.markdown("**Validation exceptions**")
                st.write(borrower["validation_note"])
            for flag in active_flags(data(), borrower["id"]):
                st.markdown(f"**{flag['category']} · {flag['severity']}**")
                st.write(flag["explanation"])
                st.caption(f"Proposed action: {flag['action'] or 'Pending'}")
    with right:
        with st.form(f"preview_manager_review_{borrower['id']}"):
            st.subheader("Your review")
            comment = st.text_area(
                "Manager observations",
                value=borrower["manager_note"],
                height=120,
                key=f"preview_manager_note_{borrower['id']}",
                placeholder="What changes your risk view? What should the board know?",
            )
            recommendation = st.text_area(
                "Recommendation",
                value=""
                if borrower["recommendation"] == "Pending manager review"
                else borrower["recommendation"],
                key=f"preview_manager_recommendation_{borrower['id']}",
                placeholder="e.g. Maintain exposure with weekly liquidity reporting.",
            )
            disposition = st.selectbox(
                "Next step", ["Continue monitoring", "Request remediation", "Resolve flag"]
            )
            c1, c2 = st.columns(2)
            save = c1.form_submit_button("Save comment", width="stretch")
            review = c2.form_submit_button("Mark reviewed", type="primary", width="stretch")
            if save or review:
                open_requests = [
                    r
                    for r in data()["requests"]
                    if r["borrower_id"] == borrower["id"] and r["status"] == "Open"
                ]
                if not comment.strip() and not recommendation.strip():
                    st.warning("Add an observation or recommendation before saving.")
                elif review and not borrower["submitted"]:
                    st.warning(
                        "Ask the analyst to submit this assessment before completing review."
                    )
                elif review and open_requests:
                    st.warning(
                        "An analysis request is still open. Review its response "
                        "before completing this case."
                    )
                elif review and not recommendation.strip():
                    st.warning("Add a recommendation before marking the borrower reviewed.")
                else:
                    borrower["manager_note"] = comment.strip()
                    if recommendation.strip():
                        borrower["recommendation"] = recommendation.strip()
                    if comment.strip():
                        data()["comments"].append(
                            {
                                "borrower_id": borrower["id"],
                                "text": comment.strip(),
                                "at": timestamp(),
                            }
                        )
                    if review:
                        for flag in active_flags(data(), borrower["id"]):
                            flag["status"] = (
                                "Resolved" if disposition == "Resolve flag" else "Reviewed"
                            )
                            flag["disposition"] = disposition
                        for request in data()["requests"]:
                            if (
                                request["borrower_id"] == borrower["id"]
                                and request["status"] == "Response ready"
                            ):
                                request["status"] = "Accepted"
                        log_event(
                            data(),
                            borrower["id"],
                            "Manager review completed",
                            recommendation.strip(),
                        )
                    flash("Review completed." if review else "Manager comment saved.")
                    st.rerun()
    with st.expander("Request another analysis", expanded=False):
        st.caption(
            "Ask the analyst for a revised view, or run a sample context-only review directly."
        )
        with st.form(f"preview_request_form_{borrower['id']}"):
            question = st.text_input(
                "Analysis question", placeholder="What happens if the earnings recovery is delayed?"
            )
            context = st.text_area(
                "Additional context / data",
                placeholder="Include new information, source dates and assumptions.",
            )
            owner_col, due_col = st.columns(2)
            owner = owner_col.text_input("Assigned analyst", value=borrower["analyst"])
            due = due_col.date_input("Due date", value=date.today() + timedelta(days=7))
            c1, c2 = st.columns(2)
            requested = c1.form_submit_button(
                "Send analysis request", type="primary", width="stretch"
            )
            direct = c2.form_submit_button("Run context-only sample review", width="stretch")
            if requested or direct:
                if not question.strip():
                    st.warning("Add the question you want the new review to address.")
                elif direct:
                    simulate_review(
                        data(), borrower["id"], f"{question.strip()}\n\n{context.strip()}"
                    )
                    flash("Supplemental sample review created. No agents were called.")
                    st.rerun()
                else:
                    request_analysis(
                        data(),
                        borrower["id"],
                        question.strip(),
                        context.strip(),
                        owner.strip() or borrower["analyst"],
                        due.isoformat(),
                    )
                    flash("Request sent. Open Borrower analysis to try the response workflow.")
                    st.rerun()
    requests = [r for r in data()["requests"] if r["borrower_id"] == borrower["id"]]
    for request in requests:
        with st.container(border=True):
            st.markdown(f"**{request['id']} · {request['status']}**  \n{request['question']}")
            st.caption(f"{request['owner']} · Due {request['due']}")
            if request["response"]:
                st.write(request["response"])


def render_risk_review() -> None:
    page_header(
        "Risk manager / Review",
        "Focus on what needs a decision",
        "Review the analyst's findings, challenge the assumptions, and agree the next action.",
    )
    borrower = borrower_picker("preview_risk_borrower", "Select borrower to review")
    borrowers = list(data()["borrowers"].values())
    flags = active_flags(data())
    pending = {
        f["borrower_id"] for f in flags if f["status"] in {"Pending review", "Changes requested"}
    }
    open_requests = [r for r in data()["requests"] if r["status"] == "Open"]
    metrics = st.columns(4)
    metrics[0].metric("Borrowers", len(borrowers))
    metrics[1].metric("Awaiting review", len(pending))
    metrics[2].metric("Open analysis requests", len(open_requests))
    metrics[3].metric("Breaches", sum(b["status"] == "Breach" for b in borrowers))
    top, board = st.columns([3, 1])
    top.subheader("Flagged borrower queue")
    if board.button("Prepare board report →", width="stretch"):
        navigate("Board report")
    view = st.radio(
        "Queue view",
        ["All flagged", "Pending review", "Changes requested", "Reviewed"],
        horizontal=True,
        key="preview_queue_filter",
        label_visibility="collapsed",
    )
    visible_flags = [flag for flag in flags if view == "All flagged" or flag["status"] == view]
    rows = [
        {
            "Borrower": data()["borrowers"][flag["borrower_id"]]["name"],
            "Severity": flag["severity"],
            "Reason": flag["explanation"],
            "Analyst": data()["borrowers"][flag["borrower_id"]]["analyst"],
            "Status": flag["status"],
            "Period": PERIOD,
        }
        for flag in visible_flags
    ]
    if rows:
        st.caption("Click a row to show that borrower's analysis and review below.")
        revision = st.session_state.get("preview_risk_queue_revision", 0)
        table_key = f"preview_risk_queue_{revision}_" + "_".join(f["id"] for f in visible_flags)
        borrower_ids = tuple(flag["borrower_id"] for flag in visible_flags)
        event = preview_table(
            rows,
            key=table_key,
            selectable=True,
            on_select=lambda: select_risk_queue_row(table_key, borrower_ids),
            selection_mode=["single-row", "single-cell"],
        )
        # A table recreated after navigation starts with an empty selection.
        # Remember that state too, rather than retaining an old click signature.
        st.session_state._preview_risk_queue_selection = {
            "key": table_key,
            "rows": tuple(event.selection.rows),
            "cells": tuple(tuple(cell) for cell in event.selection.cells),
        }
    else:
        st.info("No flagged borrowers in this queue view.")
    flagged_ids = {f["borrower_id"] for f in data()["flags"]}
    untriaged = [b for b in borrowers if b["status"] == "Breach" and b["id"] not in flagged_ids]
    if untriaged:
        notice("Breach awaiting analyst triage: " + ", ".join(b["name"] for b in untriaged) + ".")
    render_manager_detail(borrower)


def render_report_content(report: dict) -> None:
    st.markdown(
        '<div class="preview-eyebrow">Board risk committee / Portfolio monitoring</div>',
        unsafe_allow_html=True,
    )
    st.header(report["title"])
    st.caption(
        f"{report['period']} · {report.get('id', 'Draft')}"
        f" · {report.get('created', 'Not finalized')}"
    )
    metrics = st.columns(3)
    metrics[0].metric("Portfolio borrowers", report.get("borrowers", len(data()["borrowers"])))
    metrics[1].metric("Borrowers in report", len(report["items"]))
    metrics[2].metric("Covenant breaches", report.get("breaches", 0))
    st.subheader("Executive summary")
    st.write(report["summary"])
    st.subheader("Borrowers requiring attention")
    preview_table(
        [
            {
                "Borrower": item["name"],
                "Priority": item["severity"],
                "Compliance": item["status"],
                "Review": item["review_state"],
                "Explanation": item["explanation"],
            }
            for item in report["items"]
        ]
    )
    for item in report["items"]:
        with st.container(border=True):
            st.subheader(item["name"])
            st.markdown(
                status_chip(item["status"]) + chip(item["review_state"]),
                unsafe_allow_html=True,
            )
            st.caption(f"{item['borrower_id']} · {item['period']} · Assessment v{item['version']}")
            st.markdown("**Why flagged**")
            st.write(item["explanation"])
            st.markdown("**Risk analysis**")
            st.write(item["risk"])
            st.caption(
                "Mitigants to verify: earnings stabilization, liquidity and a credible action plan."
            )
            st.markdown("**Analyst observation**")
            st.write(item["analyst_report"])
            st.markdown("**Manager recommendation**")
            st.write(item["recommendation"] or "Pending manager review")
            if item["manager_note"]:
                st.caption(item["manager_note"])
            for request in item["requests"]:
                st.caption(
                    f"Outstanding: {request['question']} · {request['status']}"
                    f" · Due {request['due']}"
                )
    st.caption(
        "UI preview · Entirely illustrative sample data · No live risk analysis or verification"
    )


def render_board_report() -> None:
    page_header(
        "Risk manager / Reporting",
        "A clear view for the board",
        "Turn reviewed exceptions into a concise report with a recommendation for every borrower.",
    )
    reports = data()["reports"]
    options = ["New report", *[report["id"] for report in reversed(reports)]]
    lookup = {report["id"]: report for report in reports}
    selection = st.selectbox(
        "Report",
        options,
        key="preview_report_selection",
        format_func=lambda report_id: (
            "Create a new board report"
            if report_id == "New report"
            else f"{report_id} · {lookup[report_id]['title']} · Finalized"
        ),
    )
    if selection != "New report":
        report = lookup[selection]
        st.success("Finalized sample report. Later preview changes do not alter this snapshot.")
        render_report_content(report)
        return
    items = board_items(data())
    draft = data()["board_draft"]
    pending = sum(item["recommendation"] == "Pending manager review" for item in items)
    notice(
        f"{len(items)} borrowers will be included, covering active flags and untriaged breaches. "
        f"{pending} still need a manager recommendation. Pending items remain visible."
    )
    with st.form("preview_board_form"):
        title_col, period_col = st.columns([2, 1])
        title = title_col.text_input(
            "Report title", value=draft.get("title", "Quarterly credit risk review")
        )
        period = period_col.selectbox("Reporting period", [PERIOD])
        summary = st.text_area(
            "Executive summary",
            value=draft.get("summary", DEFAULT_SUMMARY),
            height=130,
        )
        st.markdown("**Borrower recommendations**")
        st.caption("Edit the board-facing recommendation. The source assessment remains unchanged.")
        overrides = {}
        for item in items:
            overrides[item["borrower_id"]] = st.text_area(
                item["name"],
                value=draft.get("recommendations", {}).get(
                    item["borrower_id"],
                    item["recommendation"],
                ),
                height=80,
                key=f"preview_board_recommendation_{item['borrower_id']}",
            )
        save_col, final_col = st.columns(2)
        save = save_col.form_submit_button("Save report draft", width="stretch")
        finalize = final_col.form_submit_button(
            "Finalize sample report", type="primary", width="stretch"
        )
        if save or finalize:
            if not title.strip() or not summary.strip():
                st.warning("Add a report title and executive summary.")
            else:
                data()["board_draft"] = {
                    "title": title.strip(),
                    "summary": summary.strip(),
                    "recommendations": overrides,
                }
                if finalize:
                    for item in items:
                        item["recommendation"] = (
                            overrides[item["borrower_id"]].strip() or "Pending manager review"
                        )
                    report = finalize_report(data(), title.strip(), period, summary.strip(), items)
                    st.session_state._preview_next_report = report["id"]
                    flash(f"{report['id']} finalized in this preview session.")
                else:
                    flash("Board report draft saved in this session.")
                st.rerun()
    with st.expander("Preview report layout"):
        preview_items = deepcopy(items)
        for item in preview_items:
            item["recommendation"] = overrides[item["borrower_id"]] or "Pending manager review"
        render_report_content(
            {
                "title": title,
                "period": period,
                "summary": summary,
                "items": preview_items,
                "breaches": sum(b["status"] == "Breach" for b in data()["borrowers"].values()),
            }
        )


def main() -> None:
    st.set_page_config(
        page_title="Credit Monitor · POC",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    if "preview_data" not in st.session_state:
        st.session_state.preview_data = initial_preview()
        st.session_state.preview_selected_borrower = "SYN002"
    if "_preview_next_page" in st.session_state:
        st.session_state.preview_page = st.session_state.pop("_preview_next_page")
    if "_preview_next_report" in st.session_state:
        st.session_state.preview_report_selection = st.session_state.pop("_preview_next_report")
    render_preview_style()
    render_sidebar()
    if st.session_state.preview_page != "Borrower analysis":
        st.session_state.preview_chat_expanded = False
    if st.session_state.preview_page == "Portfolio":
        st.markdown(
            '<div class="preview-ribbon"><span><b>CONNECTED PORTFOLIO</b> &nbsp; '
            "Existing calculation services and credit review agents</span>"
            "<span>Synthetic inputs &nbsp; / &nbsp; Saved locally</span></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="preview-ribbon"><span><b>UI PREVIEW</b> &nbsp; '
            "Sample workflow · This section is not connected yet</span>"
            "<span>Session-only changes &nbsp; / &nbsp; Q3 2026</span></div>",
            unsafe_allow_html=True,
        )
    if "_preview_flash" in st.session_state:
        st.toast(st.session_state.pop("_preview_flash"))
    {
        "Portfolio": render_portfolio,
        "Borrower analysis": render_borrower_analysis,
        "Documents & data": render_documents,
        "Risk review": render_risk_review,
        "Board report": render_board_report,
    }[st.session_state.preview_page]()


if __name__ == "__main__":
    main()
