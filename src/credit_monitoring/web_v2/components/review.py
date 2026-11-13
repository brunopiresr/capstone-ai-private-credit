"""Readable, tabbed presentation of a saved V2 credit review."""

import streamlit as st

from credit_monitoring.domain.credit_review import CreditReviewResult
from credit_monitoring.web.portfolio import formatted_time


def render_credit_review(review: CreditReviewResult) -> None:
    """Present the recommendation first, keeping diagnostics available on demand."""
    st.markdown("#### AI Credit Review Results")
    st.caption(
        f"Review {review.review_id} · {formatted_time(review.created_at.isoformat())} · "
        f"Status: {review.status.title()}"
    )
    recommendation_tab, bullish_tab, bearish_tab = st.tabs(["Recommendation", "Bullish", "Bearish"])
    with recommendation_tab:
        recommendation = review.recommendation
        st.markdown(f"**{recommendation.action.title()}**")
        st.write(recommendation.rationale)
        for judgment in recommendation.argument_judgments:
            st.markdown(
                f"- **{judgment.perspective.title()} · {judgment.disposition}:** "
                f"{judgment.rationale}"
            )
        for condition in recommendation.conditions:
            st.markdown(f"- {condition}")
        st.caption(f"Evidence confidence: {recommendation.confidence}")
        st.caption(recommendation.confidence_explanation)
        st.caption(f"Model: {review.recommendation_execution.model}")
        st.caption("Advisory result; analyst and manager decisions remain separate.")
        with st.expander("Recommendation evidence and open questions"):
            st.json(recommendation.model_dump(mode="json"))

    warnings = list(review.issues)
    if review.status != "complete":
        warnings.insert(0, f"This review is {review.status}. Available results are retained.")
    if review.recommendation_execution.status != "complete":
        warnings.append(
            f"Recommendation: {review.recommendation_execution.status} · "
            f"{review.recommendation_execution.error_code or 'Unavailable'}"
        )

    for tab, name, perspective in (
        (bullish_tab, "Bullish", review.bullish),
        (bearish_tab, "Bearish", review.bearish),
    ):
        with tab:
            analysis = perspective.analysis
            if analysis is None:
                st.caption(f"{name} analysis unavailable. See warnings for details.")
                warnings.append(
                    f"{name}: {perspective.execution.status} · "
                    f"{perspective.execution.error_code or 'Unavailable'}"
                )
            else:
                st.markdown(f"**{analysis.thesis}**")
                for argument in analysis.arguments:
                    st.markdown(f"- {argument.statement}")
                st.caption(f"Evidence confidence: {analysis.confidence}")
                st.caption(analysis.confidence_explanation)
                with st.expander(f"{name} argument rationales, evidence and limitations"):
                    for argument in analysis.arguments:
                        st.markdown(f"**{argument.argument_id} · {argument.statement}**")
                        st.write(argument.rationale)
                        st.write(argument.credit_implication)
                        st.caption("Evidence: " + ", ".join(argument.evidence_ids))
                        for assumption in argument.assumptions:
                            st.caption(f"Assumption: {assumption}")
                    st.json(analysis.model_dump(mode="json"))
            st.caption(f"Model: {perspective.execution.model}")

    warnings = list(dict.fromkeys(warnings))
    if warnings:
        with st.expander(f"⚠ Warnings ({len(warnings)})", expanded=False):
            for warning in warnings:
                st.write(warning)
    with st.expander("Review question, criteria and supporting snapshot"):
        if review.decision_context:
            st.write(review.decision_context.question)
            for criterion in review.decision_context.credit_criteria:
                st.markdown(f"- {criterion}")
        st.caption("News is explicitly unavailable unless an actual provider supplied it.")
        st.json(review.snapshot.model_dump(mode="json"), expanded=False)
