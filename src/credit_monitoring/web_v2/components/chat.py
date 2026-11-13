"""Interactive AI Assistant component with suggested prompt chips for web_v2."""

import os
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4

import logfire
import streamlit as st
from opentelemetry._logs import SeverityNumber, get_logger

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.events import AgentEvent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.borrower_workflow import (
    BorrowerWorkflow,
    SavedAssessmentChat,
)
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.observability import SessionContext, session_scope
from credit_monitoring.observability.configuration import (
    is_observability_configured,
    span,
)
from credit_monitoring.web.assessment import render_answer
from credit_monitoring.web.telemetry import with_web_session
from credit_monitoring.web.workspace import ask_about_assessment

FEEDBACK_CATEGORIES = (
    "Helpful",
    "Accuracy",
    "Relevance",
    "Completeness",
    "Clarity",
    "Evidence/citations",
    "Other",
)


def submit_feedback(
    message: dict,
    assessment: RiskAssessment,
    key_prefix: str,
    kind: str,
    value: int,
    *,
    category: str | None = None,
    comment: str = "",
) -> None:
    """Submit each feedback type once per response; telemetry delivery is best effort."""
    if kind not in {"feedback", "review"}:
        raise ValueError("Unknown feedback type.")
    if type(value) is not int or value not in (range(2) if kind == "feedback" else range(1, 6)):
        raise ValueError("Choose a valid rating.")
    if kind == "review" and category not in FEEDBACK_CATEGORIES:
        raise ValueError("Choose a review category.")
    comment = comment.strip()
    if len(comment) > 2000:
        raise ValueError("Review messages must be 2,000 characters or fewer.")
    if kind in message:
        return

    feedback = {
        "feedback_id": str(uuid4()),
        "submitted_at": datetime.now(UTC).isoformat(),
        "score": value,
        "category": category,
        "comment": comment,
    }
    message[kind] = feedback
    # Retain the submission even when export is disabled or unavailable. There is
    # deliberately no local queue, retry, or claim of confirmed cloud delivery.
    if not is_observability_configured():
        return
    origin = message.get("response_origin", "unknown")
    target = "Structured fallback" if origin == "structured_fallback" else "Credit assessment agent"
    attributes = {
        "event_name": "user.feedback",
        "feedback_id": feedback["feedback_id"],
        "submitted_at": feedback["submitted_at"],
        "feedback_type": "quick" if kind == "feedback" else "review",
        "interaction_id": message["interaction_id"],
        "assessment_run_id": assessment.assessment_run_id,
        "borrower_id": assessment.borrower_id,
        "period_end": assessment.period_end.isoformat(),
        "information_cutoff": assessment.information_cutoff.isoformat(),
        "interface": "web_v2",
        "mode": key_prefix,
        "response_origin": origin,
        "complete": message.get("answer").complete if "answer" in message else True,
        "gen_ai.evaluation.target": target,
        "gen_ai.evaluation.name": "user_helpfulness" if kind == "feedback" else "user_review_score",
        "gen_ai.evaluation.score.value": float(value),
    }
    if kind == "feedback":
        attributes["rating"] = "positive" if value else "negative"
    else:
        attributes.update(category=category, comment=comment, has_comment=bool(comment))
    if origin == "agent":
        attributes["gen_ai.agent.name"] = target
    if model := message.get("model"):
        attributes["gen_ai.request.model"] = model
    if conversation_id := message.get("conversation_id"):
        attributes["gen_ai.conversation.id"] = conversation_id
    if web_id := logfire.get_baggage().get("session.id"):
        attributes["session.id"] = web_id
    try:
        parent_context = message.get("agent_context")
        with logfire.attach_context(parent_context) if parent_context else nullcontext():
            get_logger(__name__).emit(
                event_name="gen_ai.evaluation.result",
                severity_number=SeverityNumber.INFO,
                body="User feedback on assistant response",
                attributes=attributes,
            )
    except Exception:
        # Export problems must not interrupt chat or replay a submitted review.
        pass


def render_feedback(message: dict, assessment: RiskAssessment, key_prefix: str) -> None:
    """Rate the displayed answer without running the agent again on form submission."""
    interaction_id = message.setdefault("interaction_id", str(uuid4()))
    key = f"{key_prefix}_feedback_{interaction_id}"

    def save(kind: str) -> None:
        try:
            submit_feedback(
                message,
                assessment,
                key_prefix,
                kind,
                st.session_state.get(f"{key}_rating" if kind == "feedback" else f"{key}_score"),
                category=st.session_state.get(f"{key}_category") if kind == "review" else None,
                comment=st.session_state.get(f"{key}_comment", "") if kind == "review" else "",
            )
        except ValueError as error:
            message[f"{kind}_error"] = str(error)
        else:
            message.pop(f"{kind}_error", None)

    # Restore saved values when disabling widgets changes their Streamlit identity.
    if "feedback" in message:
        saved = message["feedback"]
        st.session_state[f"{key}_rating"] = saved.get(
            "score", 1 if saved.get("rating") == "positive" else 0
        )
    if "review" in message:
        for field in ("score", "category", "comment"):
            st.session_state[f"{key}_{field}"] = message["review"][field]

    st.markdown("**Rate this answer**")
    with st.form(key):
        st.feedback("thumbs", key=f"{key}_rating", disabled="feedback" in message)
        st.form_submit_button(
            "Send feedback",
            disabled="feedback" in message,
            on_click=with_web_session(save),
            args=("feedback",),
        )
    if error := message.get("feedback_error"):
        st.info(error)
    if "feedback" in message:
        st.caption("Thanks for your rating.")

    with st.expander("Add detailed review"):
        reviewed = "review" in message
        with st.form(f"{key}_review"):
            st.selectbox(
                "Review score (1–5)",
                range(1, 6),
                index=None,
                key=f"{key}_score",
                disabled=reviewed,
            )
            st.selectbox(
                "Review category",
                FEEDBACK_CATEGORIES,
                index=None,
                key=f"{key}_category",
                disabled=reviewed,
            )
            st.text_area(
                "Review message (optional)",
                key=f"{key}_comment",
                max_chars=2000,
                disabled=reviewed,
            )
            st.form_submit_button(
                "Submit review",
                disabled=reviewed,
                on_click=with_web_session(save),
                args=("review",),
            )
        if error := message.get("review_error"):
            st.info(error)
        if reviewed:
            st.caption("Thanks for your review.")


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
                on_click=with_web_session(on_select),
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


def _fallback_message(
    assessment: RiskAssessment, question: str, *, error_type: str | None = None
) -> dict:
    """Keep fallback feedback separate from agent scores and linked to its response."""
    with span(
        "assistant.fallback",
        borrower_id=assessment.borrower_id,
        assessment_run_id=assessment.assessment_run_id,
        response_origin="structured_fallback",
    ):
        context = logfire.get_context() if is_observability_configured() else None
        content = generate_structured_fallback(assessment, question)
        if error_type:
            content += f"\n\n*(Agent notice: {error_type})*"
        return {
            "role": "assistant",
            "content": content,
            "response_origin": "structured_fallback",
            "agent_context": context,
        }


def _answer_question(workflow: BorrowerWorkflow, assessment: RiskAssessment, question: str) -> dict:
    """Answer from one immutable assessment using the existing agent or offline fallback."""
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return _fallback_message(assessment, question)
    review = workflow.portfolio.repository.latest_review(assessment.assessment_run_id)
    adapter = SavedAssessmentChat(workflow, assessment)
    adapter.allow_recalculation = False
    adapter.reason = f"Chat query: {question}"
    adapter.prediction_mode = "Logistic Regression"
    agent_context = None

    async def remember_agent_span(event: AgentEvent) -> None:
        nonlocal agent_context
        # model_start is yielded inside the native agent run, before its model
        # request span opens. Later output callbacks may be inside child spans.
        if event.kind == "model_start" and agent_context is None and is_observability_configured():
            agent_context = logfire.get_context()

    conversation = CreditAssessmentAgent(
        assessment_service=adapter,
        model=os.getenv("LLM_MODEL") or DEFAULT_MODEL,
        event_stream_handler=remember_agent_span,
    ).start_conversation(borrower_id=assessment.borrower_id)
    answer = ask_about_assessment(conversation, question, assessment, review=review)
    if answer:
        return {
            "role": "assistant",
            "answer": answer,
            "conversation_id": conversation.session_id,
            "agent_context": agent_context,
            "response_origin": "agent",
            "model": os.getenv("LLM_MODEL") or DEFAULT_MODEL,
        }
    return {
        "role": "assistant",
        "content": "Assistant completed conversation turn.",
        "rateable": False,
    }


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
        session_key = f"{scope}_conversation_session"
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
                st.session_state.pop(session_key, None)

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
                    if message["role"] == "assistant" and message.get("rateable", True):
                        render_feedback(message, assessment, key_prefix)

        st.chat_input(
            f"Ask about {assessment.borrower_id}…",
            key=input_key,
            disabled=busy,
            on_submit=with_web_session(enqueue_input),
        )
        if st.session_state[state_key]:
            st.button(
                "Clear Chat",
                key=f"{key_prefix}_clear_{assessment.assessment_run_id}",
                disabled=busy,
                on_click=with_web_session(clear_history),
            )

        # Controls above are already disabled and the user message is visible when work starts.
        question = st.session_state.pop(pending_key, None)
        if question:
            interaction_id = str(uuid4())
            try:
                with (
                    session_scope(st.session_state.setdefault(session_key, SessionContext())),
                    logfire.set_baggage(interaction_id=interaction_id),
                    st.spinner("Answering…"),
                ):
                    try:
                        message = _answer_question(workflow, assessment, question)
                    except Exception as error:
                        try:
                            message = _fallback_message(
                                assessment, question, error_type=type(error).__name__
                            )
                        except Exception:
                            message = {
                                "role": "assistant",
                                "content": "Unable to answer this question. Please try again.",
                                "rateable": False,
                            }
                    message["interaction_id"] = interaction_id
                    st.session_state[state_key].append(message)
            finally:
                st.session_state[busy_key] = False
            st.rerun()
