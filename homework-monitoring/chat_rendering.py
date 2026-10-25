"""Streamlit presentation of public progress and authoritative service results."""

from collections.abc import Callable

import streamlit as st
from monitoring_backend import ChatTurn

from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.web.assessment import render_prediction, render_results, render_verification


def live_response(turn: ChatTurn):
    """Create placeholders once; callbacks update them on the Streamlit script thread."""
    status = st.status("Working…", expanded=not turn.finished or bool(turn.error))
    with status:
        activity = st.empty()
    answer = st.empty()

    def update(current: ChatTurn) -> None:
        symbols = {"running": "◌", "complete": "✓", "error": "!", "skipped": "–"}
        activity.markdown(
            "\n\n".join(f"{symbols[item.state]} {item.label}" for item in current.activities)
            or "Starting the agent…"
        )
        status.update(
            label=(
                "Incomplete — see results and activity"
                if current.error
                else "Complete"
                if current.finished
                else "Working…"
            ),
            state="error" if current.error else "complete" if current.finished else "running",
            expanded=not current.finished or bool(current.error),
        )
        if current.content:
            answer.markdown(current.content)

    update(turn)
    return update


def _toggle_source(key: str, index: int, on_source_open: Callable[[int], None] | None) -> None:
    st.session_state[key] = not st.session_state.get(key, False)
    if st.session_state[key] and on_source_open is not None:
        on_source_open(index)


def response_details(
    turn: ChatTurn, *, on_source_open: Callable[[int], None] | None = None
) -> None:
    with st.expander("Tools called"):
        if not turn.tools:
            st.caption("No tools were called in this interaction.")
        for tool in turn.tools:
            st.write(tool["name"])
            st.json(tool)
    if turn.sources:
        with st.expander("Sources"):
            for index, source in enumerate(turn.sources):
                key = f"monitoring_ui_source_{turn.interaction_id}_{index}"
                st.button(
                    f"View citation {index + 1}", key=f"{key}_button",
                    on_click=_toggle_source, args=(key, index, on_source_open),
                )
                if st.session_state.get(key, False):
                    st.write(f"{source['document_id']}: {source['citation']}")
    if turn.review is None:
        return
    review = turn.review
    st.caption(f"Review: {review.review_id} · Status: {review.status}")
    with st.expander("Calculations, verification and ML"):
        assessment = RiskAssessment.model_validate(review.snapshot.assessment_data)
        render_results(assessment)
        render_verification(assessment)
        render_prediction(assessment)
    for title, perspective in (
        ("Bullish analysis", review.bullish),
        ("Bearish analysis", review.bearish),
    ):
        with st.expander(title):
            st.caption(f"Agent status: {perspective.execution.status}")
            if perspective.analysis is not None:
                st.markdown(perspective.analysis.thesis)
                st.json(perspective.analysis.model_dump(mode="json"))
            else:
                st.warning(perspective.execution.error_code or "This review was skipped.")
    with st.expander("Final recommendation and limitations"):
        st.write(f"Action: {review.recommendation.action}")
        st.markdown(review.recommendation.rationale)
        st.json(review.recommendation.model_dump(mode="json"))
        for issue in review.issues:
            st.warning(issue)
    with st.expander("Review evidence and source records"):
        st.caption(
            f"Borrower: {review.snapshot.borrower_id} · Period: {review.snapshot.period_end} · "
            f"Cutoff: {review.snapshot.information_cutoff} · "
            f"Assessment: {review.snapshot.assessment_run_id}"
        )
        st.json(review.snapshot.prompt_context())
