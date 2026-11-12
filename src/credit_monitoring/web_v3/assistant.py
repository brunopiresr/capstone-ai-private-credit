"""Wide assistant with a single editable composer and assessment-scoped memory."""

import os

import streamlit as st

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.borrower_workflow import SavedAssessmentChat
from credit_monitoring.config.settings import DEFAULT_APP_PREDICTION_MODE
from credit_monitoring.web.assessment import render_answer
from credit_monitoring.web.workspace import ask_about_assessment
from credit_monitoring.web_v3.analyst import credentials
from credit_monitoring.web_v3.state import go


def render_assistant(services, assessment) -> None:
    rid = assessment.assessment_run_id
    st.subheader("Credit assistant")
    st.caption(
        "Reads this saved assessment. Answers retain the model's original wording and citations."
    )
    if not credentials():
        st.info(
            "Model access is not configured. Saved conversations remain readable; "
            "ask the operator to enable AI."
        )
    chats = st.session_state.setdefault("v3_chats", {})
    state = chats.setdefault(rid, {"messages": []})
    review = services.analyst.portfolio.repository.latest_review(rid)
    review_id = review.review_id if review else None
    if "review_id" in state and state["review_id"] != review_id:
        st.info(
            "AI analysis changed since the previous turn. New questions use "
            "the current saved analysis."
        )
    for message in state["messages"]:
        with st.chat_message(message["role"]):
            if "answer" in message:
                render_answer(message["answer"])
            else:
                st.markdown(message["content"])
    if not state["messages"]:
        st.info("Ask about covenant headroom, evidence gaps, or the saved credit analysis.")
    draft_key = f"v3_chat_draft_{rid}"
    if state.pop("clear_draft", False):
        st.session_state[draft_key] = ""
    service = services.analyst.portfolio.follow_up_service
    saved = None
    if service:
        try:
            saved = service.load(assessment, review)
        except ValueError as error:
            st.info(str(error))
    with st.expander("Suggested questions"):
        if saved:
            for i, suggestion in enumerate(saved.output.questions):
                if st.button(suggestion.question, key=f"v3btn_suggestion_{rid}_{i}"):
                    if st.session_state.get(draft_key, "").strip():
                        st.info("Your draft is kept. Clear it before choosing another suggestion.")
                    else:
                        st.session_state[draft_key] = suggestion.question
                st.caption(suggestion.reason)
        else:
            st.caption("No generated suggestions saved. You can write your own question below.")
        if service and st.button(
            "Regenerate suggestions" if saved else "Generate suggestions",
            key="v3btn_generate_suggestions",
            disabled=not credentials(),
        ):
            try:
                with st.spinner("Generating questions from the saved analysis…"):
                    service.generate(assessment, review, regenerate=bool(saved))
            except Exception as error:
                st.warning(
                    f"Suggestions unavailable ({type(error).__name__}). Earlier saved "
                    f"work is retained."
                )
            else:
                st.rerun()
    question = st.text_area(
        "Your question",
        key=draft_key,
        height=110,
        placeholder="Ask about the selected borrower and saved version…",
    )
    allow = st.checkbox("Allow a new assessment for this question", key=f"v3_chat_recalc_{rid}")
    st.caption(
        "Recalculation creates a new saved version and requires fresh validation. "
        "Otherwise, questions only read saved results."
    )
    send, clear = st.columns([1, 1])
    if send.button(
        "Send question",
        key="v3btn_chat_send",
        type="primary",
        disabled=not credentials() or not question.strip(),
    ):
        state["messages"].append({"role": "user", "content": question.strip()})
        adapter = state.get("adapter")
        try:
            if "conversation" not in state or state["conversation"].closed:
                adapter = SavedAssessmentChat(services.analyst, assessment)
                state["adapter"] = adapter
                state["conversation"] = CreditAssessmentAgent(
                    assessment_service=adapter, model=os.getenv("LLM_MODEL") or DEFAULT_MODEL
                ).start_conversation(borrower_id=assessment.borrower_id)
            adapter.allow_recalculation = allow
            adapter.new_assessment = None
            adapter.reason = f"Chat request: {question.strip()}"
            adapter.prediction_mode = st.session_state.get(
                "v3_prediction", DEFAULT_APP_PREDICTION_MODE
            )
            with st.spinner("Reading saved evidence…"):
                answer = ask_about_assessment(
                    state["conversation"], question.strip(), assessment, review=review
                )
            state["messages"].append(
                {"role": "assistant", "answer": answer}
                if answer
                else {"role": "assistant", "content": "Conversation closed."}
            )
            state["review_id"] = review_id
            state["clear_draft"] = True
        except Exception as error:
            state["messages"].append(
                {
                    "role": "assistant",
                    "content": (
                        f"Assistant unavailable ({type(error).__name__}). Saved work is retained. "
                        f"You can retry your question."
                    ),
                }
            )
        if adapter and adapter.new_assessment:
            st.session_state.v3_next_run = adapter.new_assessment.assessment_run_id
            go("Borrower", section="Overview")
        st.rerun()
    if clear.button("Clear conversation", key="v3btn_chat_clear", disabled=not state["messages"]):
        if "conversation" in state:
            state["conversation"].close()
        chats.pop(rid)
        st.rerun()
