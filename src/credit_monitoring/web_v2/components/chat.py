"""Interactive AI Assistant component with suggested prompt chips for web_v2."""

import os
from collections.abc import Callable

import streamlit as st

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.borrower_workflow import (
    BorrowerWorkflow,
    SavedAssessmentChat,
)
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.web.assessment import render_answer
from credit_monitoring.web.workspace import ask_about_assessment


def render_prompt_chips(
    prompts: list[str],
    on_select: Callable[[str], None],
    key_prefix: str,
) -> None:
    """Render clickable prompt chips."""
    st.caption("Suggested Questions:")
    # Render chips in a compact wrap or 2x2 grid
    cols = st.columns(min(len(prompts), 3))
    for idx, prompt in enumerate(prompts):
        col = cols[idx % len(cols)]
        if col.button(prompt, key=f"{key_prefix}_chip_{idx}", use_container_width=True):
            on_select(prompt)


def generate_structured_fallback(assessment: RiskAssessment, question: str) -> str:
    """Generate an authoritative rule-based answer when LLM API keys are not configured."""
    q_lower = question.lower()
    lines = [
        f"**Analysis for {assessment.borrower_id} (Reporting Period: {assessment.period_end})**:"
    ]

    if (
        "headroom" in q_lower
        or "covenant" in q_lower
        or "coverage" in q_lower
        or "leverage" in q_lower
    ):
        lines.append("\n**Current Covenant Status & Headroom:**")
        for res in assessment.results:
            status = res.compliance_status.upper()
            val_str = f"{res.actual_value:.2f}{res.unit or ''}"
            limit_str = f"{res.operator or ''} {res.threshold:.2f}{res.unit or ''}"
            lines.append(
                f"- **{res.covenant_type}**: Status `{status}`, Actual: `{val_str}`, "
                f"Threshold: `{limit_str}`, Headroom: `{res.headroom:.2f}`"
            )
            if res.compliance_status == "breach":
                lines.append("  ⚠️ **Breach Warning**: Actual exceeds contractual limit.")

    elif "risk" in q_lower or "downside" in q_lower or "thesis" in q_lower:
        lines.append("\n**Risk Profile Summary:**")
        if any(r.compliance_status == "breach" for r in assessment.results):
            lines.append(
                "- Primary concern is covenant breach requiring immediate triage or remediation."
            )
        else:
            lines.append("- All tested covenants are currently in compliance.")
        v_status = "Valid" if assessment.verification.is_valid else "Issues detected"
        lines.append(f"- Verification Status: {v_status}")
        if assessment.issues:
            lines.append(f"- Notable limitations: {'; '.join(assessment.issues)}")

    else:
        pass_count = sum(r.compliance_status == "compliant" for r in assessment.results)
        fail_count = sum(r.compliance_status == "breach" for r in assessment.results)
        lines.append(
            f"Assessment Run ID `{assessment.assessment_run_id}` reflects "
            f"{len(assessment.results)} covenant tests. "
            f"Covenants compliant: {pass_count}, Breaches: {fail_count}."
        )

    lines.append(
        "\n*(Note: Configure `OPENAI_API_KEY` for generative multi-step evidence synthesis.)*"
    )
    return "\n".join(lines)


def render_chat_widget(
    workflow: BorrowerWorkflow,
    assessment: RiskAssessment | None,
    suggested_prompts: list[str],
    key_prefix: str = "assistant",
    title: str = "AI Copilot",
    context_description: str | None = None,
) -> None:
    """Render the full interactive conversational assistant."""
    with st.container(border=True):
        st.subheader(f"💬 {title}")
        if context_description:
            st.caption(context_description)

        if assessment is None:
            st.info("Run or select a borrower assessment above to activate the AI copilot.")
            return

        state_key = f"{key_prefix}_chat_history_{assessment.assessment_run_id}"
        if state_key not in st.session_state:
            st.session_state[state_key] = []

        # Handle queued prompt selection from chips
        pending_key = f"{key_prefix}_pending_question"
        queued_question = st.session_state.pop(pending_key, None)

        def handle_chip_select(prompt: str) -> None:
            st.session_state[pending_key] = prompt
            st.rerun()

        # Render suggested prompt chips
        render_prompt_chips(suggested_prompts, handle_chip_select, key_prefix)

        # Message history display container
        with st.container(height=320):
            if not st.session_state[state_key]:
                st.caption(
                    "Ask any question regarding covenant calculations, evidence, or credit risks."
                )
            for msg in st.session_state[state_key]:
                with st.chat_message(msg["role"]):
                    if "answer" in msg:
                        render_answer(msg["answer"])
                    else:
                        st.markdown(msg["content"])

        # Input row
        question_input = st.chat_input(
            f"Ask about {assessment.borrower_id}…",
            key=f"{key_prefix}_input_{assessment.assessment_run_id}",
        )

        active_question = queued_question or question_input
        if active_question:
            st.session_state[state_key].append({"role": "user", "content": active_question})
            has_credentials = bool(os.getenv("OPENAI_API_KEY", "").strip())
            review = workflow.portfolio.repository.latest_review(assessment.assessment_run_id)

            if has_credentials:
                try:
                    adapter = SavedAssessmentChat(workflow, assessment)
                    adapter.allow_recalculation = False
                    adapter.reason = f"Chat query: {active_question}"
                    adapter.prediction_mode = "Logistic Regression"

                    conv = CreditAssessmentAgent(
                        assessment_service=adapter,
                        model=os.getenv("LLM_MODEL") or DEFAULT_MODEL,
                    ).start_conversation(borrower_id=assessment.borrower_id)

                    with st.spinner("Synthesizing evidence and calculations…"):
                        answer = ask_about_assessment(
                            conv, active_question, assessment, review=review
                        )

                    if answer:
                        st.session_state[state_key].append({"role": "assistant", "answer": answer})
                    else:
                        st.session_state[state_key].append(
                            {
                                "role": "assistant",
                                "content": "Assistant completed conversation turn.",
                            }
                        )
                except Exception as err:
                    # Graceful fallback on LLM connection error
                    fallback_msg = generate_structured_fallback(assessment, active_question)
                    err_notice = f"\n\n*(Agent notice: {type(err).__name__})*"
                    st.session_state[state_key].append(
                        {
                            "role": "assistant",
                            "content": f"{fallback_msg}{err_notice}",
                        }
                    )
            else:
                fallback_msg = generate_structured_fallback(assessment, active_question)
                st.session_state[state_key].append({"role": "assistant", "content": fallback_msg})

            st.rerun()

        if st.session_state[state_key]:
            if st.button("Clear Chat", key=f"{key_prefix}_clear_{assessment.assessment_run_id}"):
                st.session_state[state_key] = []
                st.rerun()
