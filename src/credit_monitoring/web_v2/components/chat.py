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
    *,
    disabled: bool = False,
) -> None:
    """Render clickable prompt chips."""
    if not prompts:
        return
    with st.container(key=f"{key_prefix}_chat_suggestions"):
        st.caption("Suggested Questions:")
        cols = st.columns(min(len(prompts), 3))
        for idx, prompt in enumerate(prompts):
            col = cols[idx % len(cols)]
            col.button(
                prompt,
                key=f"{key_prefix}_chip_{idx}",
                use_container_width=True,
                disabled=disabled,
                on_click=on_select,
                args=(prompt,),
            )


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
            val_str = (
                f"{res.actual_value:.2f}{res.unit or ''}"
                if res.actual_value is not None
                else "Unavailable"
            )
            limit_str = (
                f"{res.operator or ''} {res.threshold:.2f}{res.unit or ''}"
                if res.threshold is not None
                else "Unavailable"
            )
            headroom_str = f"{res.headroom:.2f}" if res.headroom is not None else "Unavailable"
            lines.append(
                f"- **{res.covenant_type}**: Status `{status}`, Actual: `{val_str}`, "
                f"Threshold: `{limit_str}`, Headroom: `{headroom_str}`"
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


def _answer_question(workflow: BorrowerWorkflow, assessment: RiskAssessment, question: str) -> dict:
    """Answer from one immutable assessment using the existing agent or offline fallback."""
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return {"role": "assistant", "content": generate_structured_fallback(assessment, question)}
    review = workflow.portfolio.repository.latest_review(assessment.assessment_run_id)
    adapter = SavedAssessmentChat(workflow, assessment)
    adapter.allow_recalculation = False
    adapter.reason = f"Chat query: {question}"
    adapter.prediction_mode = "Logistic Regression"
    conversation = CreditAssessmentAgent(
        assessment_service=adapter, model=os.getenv("LLM_MODEL") or DEFAULT_MODEL
    ).start_conversation(borrower_id=assessment.borrower_id)
    answer = ask_about_assessment(conversation, question, assessment, review=review)
    if answer:
        return {"role": "assistant", "answer": answer}
    return {"role": "assistant", "content": "Assistant completed conversation turn."}


def render_chat_widget(
    workflow: BorrowerWorkflow,
    assessment: RiskAssessment | None,
    suggested_prompts: list[str],
    key_prefix: str = "assistant",
    title: str = "AI Copilot",
    context_description: str | None = None,
    transcript_height: int = 320,
) -> None:
    """Render a conversation whose pending work and input lock belong to one assessment."""
    scope = f"{key_prefix}_{assessment.assessment_run_id}" if assessment else None
    active_scope_key = f"{key_prefix}_active_chat_scope"
    previous_scope = st.session_state.get(active_scope_key)
    if previous_scope != scope:
        # Discard unsent work on context changes, retaining each assessment's transcript.
        if previous_scope:
            st.session_state.pop(f"{previous_scope}_pending_question", None)
            st.session_state.pop(f"{previous_scope}_chat_busy", None)
        st.session_state[active_scope_key] = scope

    with st.container(border=True):
        st.subheader(f"💬 {title}")
        if context_description:
            st.caption(context_description)
        if assessment is None:
            st.info("Run or select a borrower assessment above to activate the AI copilot.")
            return

        state_key = f"{key_prefix}_chat_history_{assessment.assessment_run_id}"
        pending_key = f"{scope}_pending_question"
        busy_key = f"{scope}_chat_busy"
        input_key = f"{key_prefix}_input_{assessment.assessment_run_id}"
        st.session_state.setdefault(state_key, [])
        # A consumed request cannot be replayed after an interrupted Streamlit run.
        busy = bool(st.session_state.get(pending_key))
        st.session_state[busy_key] = busy

        def enqueue_question(prompt: str) -> None:
            if st.session_state.get(active_scope_key) != scope:
                return
            if st.session_state.get(busy_key) or not prompt.strip():
                return
            st.session_state[pending_key] = prompt.strip()
            st.session_state[busy_key] = True
            st.session_state[state_key].append({"role": "user", "content": prompt.strip()})

        def enqueue_input() -> None:
            enqueue_question(st.session_state.get(input_key) or "")

        def clear_history() -> None:
            if not st.session_state.get(busy_key):
                st.session_state[state_key] = []

        render_prompt_chips(suggested_prompts, enqueue_question, scope, disabled=busy)
        with st.container(height=transcript_height):
            if not st.session_state[state_key]:
                st.caption(
                    "Ask any question regarding covenant calculations, evidence, or credit risks."
                )
            for message in st.session_state[state_key]:
                with st.chat_message(message["role"]):
                    if "answer" in message:
                        render_answer(message["answer"])
                    else:
                        st.markdown(message["content"])

        st.chat_input(
            f"Ask about {assessment.borrower_id}…",
            key=input_key,
            disabled=busy,
            on_submit=enqueue_input,
        )
        if st.session_state[state_key]:
            st.button(
                "Clear Chat",
                key=f"{key_prefix}_clear_{assessment.assessment_run_id}",
                disabled=busy,
                on_click=clear_history,
            )

        # Controls above are already disabled and the user message is visible when work starts.
        question = st.session_state.pop(pending_key, None)
        if question:
            try:
                with st.spinner("Answering…"):
                    try:
                        message = _answer_question(workflow, assessment, question)
                    except Exception as error:
                        try:
                            fallback = generate_structured_fallback(assessment, question)
                            content = f"{fallback}\n\n*(Agent notice: {type(error).__name__})*"
                        except Exception:
                            content = "Unable to answer this question. Please try again."
                        message = {"role": "assistant", "content": content}
                    st.session_state[state_key].append(message)
            finally:
                st.session_state[busy_key] = False
            st.rerun()
