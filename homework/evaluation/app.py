"""A small Streamlit app for rating fresh responses to the 27 evaluation questions."""

import asyncio
import os

import streamlit as st
from dotenv import load_dotenv
from evaluation_backend import RESPONSE_CATEGORIES, EvaluationRound

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.observability import configure_observability
from credit_monitoring.paths import ROOT

PREFIX = "evaluation_ui_"


def cancel_restart(*, disabled: bool = False) -> None:
    with st.container(key="evaluation_cancel_action"):
        if st.button("Cancel / restart", disabled=disabled, width="stretch"):
            st.session_state[f"{PREFIX}summary_open"] = True


def skip_question(current: EvaluationRound) -> None:
    if st.button("Skip", width="stretch"):
        try:
            current.skip()
        except (OSError, ValueError) as error:
            st.error(f"Could not skip the question: {error}")
        else:
            st.session_state.pop(f"{PREFIX}generation_error", None)
            st.rerun()


def run_question(current: EvaluationRound, *, retry: bool = False) -> None:
    if retry:
        current.retry()
    st.session_state.pop(f"{PREFIX}generation_error", None)
    try:
        with st.spinner("Generating the agent’s answer…"):
            asyncio.run(current.generate())
    except (OSError, ValueError) as error:
        st.session_state[f"{PREFIX}generation_error"] = str(error)
    st.rerun()


def new_round(previous: EvaluationRound | None = None) -> None:
    current = EvaluationRound(
        model=os.getenv("LLM_MODEL") or DEFAULT_MODEL,
        previous_chat_id=previous.session.session_id if previous else None,
    )
    if previous is not None:
        previous.end("restart")
    for key in list(st.session_state):
        if key.startswith(PREFIX):
            del st.session_state[key]
    st.session_state[f"{PREFIX}round"] = current


@st.dialog("Evaluation summary", width="large", dismissible=False)
def evaluation_summary(current: EvaluationRound) -> None:
    try:
        rows = current.summary()
    except (OSError, ValueError) as error:
        st.error(f"Could not load the evaluation summary: {error}")
        if not current.complete and st.button("Continue evaluating"):
            st.session_state[f"{PREFIX}summary_open"] = False
            st.rerun()
        return

    submitted = sum(row["submitted"] for row in rows)
    st.write(f"{submitted} of {len(current.cases)} answers evaluated.")
    skipped = sum(row.get("status") == "skipped" for row in rows)
    if skipped:
        st.caption(f"{skipped} questions skipped.")
    st.caption("Review the rates and comments before starting again.")
    table = []
    for row in rows:
        if row.get("status") == "skipped":
            table.append({"Question ID": row["case_id"], "Rate": "Skipped", "Comments": ""})
            continue
        if not row["submitted"] and current.attempt is not None:
            key = f"{PREFIX}feedback_{current.attempt.interaction_id}"
            row["category"] = st.session_state.get(f"{key}_category")
            row["comment"] = st.session_state.get(f"{key}_comment", "")
        default_rate = "Not run" if row.get("status") == "not_run" else "Not evaluated"
        rate = RESPONSE_CATEGORIES.get(row.get("category"), row.get("rating", default_rate))
        if not row["submitted"] and row.get("category"):
            rate += " (not submitted)"
        table.append({"Question ID": row["case_id"], "Rate": rate, "Comments": row["comment"]})
    if table:
        st.dataframe(table, hide_index=True, width="stretch", row_height=64)
    else:
        st.info("No answers have been evaluated yet.")

    proceed, keep_evaluating = st.columns(2)
    with proceed:
        if st.button("Proceed to restart", type="primary"):
            try:
                new_round(current)
            except (OSError, ValueError) as error:
                st.error(f"Could not start a new evaluation: {error}")
            else:
                st.rerun()
    with keep_evaluating:
        if not current.complete and st.button("Continue evaluating"):
            st.session_state[f"{PREFIX}summary_open"] = False
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Evaluate agent responses", page_icon="📝")
    st.html("""
        <style>
        .st-key-evaluation_cancel_action button {
            background-color: #b54708;
            border-color: #b54708;
            color: white;
        }
        .st-key-evaluation_cancel_action button:hover {
            background-color: #93370d;
            border-color: #93370d;
            color: white;
        }
        .st-key-evaluation_cancel_action button:focus-visible {
            outline: 2px solid #b54708;
            outline-offset: 2px;
        }
        .st-key-evaluation_cancel_action button:disabled { opacity: 0.5; }
        </style>
    """)
    load_dotenv(ROOT / ".env", override=False)
    st.title("Evaluate agent responses")
    st.write(
        "Read each question and the agent’s answer, then choose a category and optional comment."
    )
    try:
        configure_observability()
    except Exception as error:
        st.error(f"Monitoring configuration failed ({type(error).__name__}). Check .env settings.")
        st.stop()

    credentials_available = bool(os.getenv("OPENAI_API_KEY", "").strip())
    if not credentials_available:
        st.info("Set OPENAI_API_KEY in the repository .env to generate agent answers.")

    current = st.session_state.get(f"{PREFIX}round")
    if current is not None:
        current = EvaluationRound.resume(current)
        st.session_state[f"{PREFIX}round"] = current
    if current is None:
        st.caption("27 questions · A fresh agent answer for each question")
        if st.button("Start evaluation", type="primary"):
            try:
                new_round()
            except (OSError, ValueError) as error:
                st.error(f"Could not start the evaluation: {error}")
            else:
                st.rerun()
        return

    if current.complete:
        evaluation_summary(current)
        return

    render_question(current, credentials_available)
    if st.session_state.get(f"{PREFIX}summary_open"):
        evaluation_summary(current)


def render_question(current: EvaluationRound, credentials_available: bool) -> None:
    generation_error = st.session_state.get(f"{PREFIX}generation_error")
    st.caption(f"Question {current.index + 1} of {len(current.cases)} · {current.case['case_id']}")
    st.progress(current.index / len(current.cases))

    st.subheader("Question")
    st.markdown(current.case["question"])
    if current.attempt is None:
        if generation_error:
            st.error(f"Could not prepare the answer: {generation_error}")
        run, skip, cancel = st.columns(3)
        with run:
            if st.button(
                "Run question", type="primary", disabled=not credentials_available, width="stretch"
            ):
                run_question(current)
        with skip:
            skip_question(current)
        with cancel:
            cancel_restart()
        return

    answer = current.attempt.answer
    st.subheader("Agent answer")
    if answer.get("answer"):
        st.markdown(answer["answer"])
    if answer.get("sources"):
        with st.expander("Sources"):
            for source in answer["sources"]:
                st.write(f"{source['document_id']}: {source['citation']}")
    if not answer["complete"]:
        st.error(f"The agent could not complete this answer: {answer.get('error') or 'Incomplete'}")
        if generation_error:
            st.error(f"Could not prepare the answer: {generation_error}")
        retry, skip, cancel = st.columns(3)
        with retry:
            if st.button("Retry answer", disabled=not credentials_available, width="stretch"):
                run_question(current, retry=True)
        with skip:
            skip_question(current)
        with cancel:
            cancel_restart()
        return

    key = f"{PREFIX}feedback_{current.attempt.interaction_id}"
    with st.container(border=True):
        category = st.selectbox(
            "Response category",
            options=tuple(RESPONSE_CATEGORIES),
            format_func=RESPONSE_CATEGORIES.__getitem__,
            index=None,
            placeholder="Choose a category",
            key=f"{key}_category",
        )
        comment = st.text_area("Comment (optional)", max_chars=2000, key=f"{key}_comment")
        submit, skip, cancel = st.columns(3)
        with submit:
            submitted = st.button("Submit and next", type="primary", width="stretch")
        with skip:
            skip_question(current)
        with cancel:
            cancel_restart()
    if submitted:
        if category is None:
            st.info("Choose a response category first.")
            return
        try:
            current.rate(category, comment)
        except (OSError, ValueError) as error:
            st.error(f"Feedback could not be saved: {error}")
            return
        st.rerun()


if __name__ == "__main__":
    main()
