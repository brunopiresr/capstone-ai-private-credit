"""Chat demo for evidence search, borrower review and session monitoring."""

import asyncio
import os
from pathlib import Path

import streamlit as st
from chat_rendering import live_response, response_details
from dotenv import load_dotenv
from monitoring_backend import ROOT, ChatBackend, ChatTurn

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.observability import configure_observability
from credit_monitoring.observability.configuration import capture_content_enabled

MODES = ("Evidence Search", "Credit Analysis")
MODE_DESCRIPTIONS = {
    "Evidence Search": (
        "Find passages in company filings and see the source citations supporting the answer."
    ),
    "Credit Analysis": (
        "Review one borrower's financials, covenant calculations, ML forecast, "
        "bullish and bearish views, and final recommendation."
    ),
}
PREFIX = "monitoring_ui_"
SAMPLE_QUESTIONS = {
    "Evidence Search": (
        (
            "Find covenant terms",
            "Find the financial covenant terms in FMC's local filings. Cite the document "
            "and passage supporting each threshold and testing date.",
        ),
        (
            "Locate amendments",
            "Find passages in FMC's credit agreement amendments that describe changes to "
            "leverage covenant thresholds. Include exact source citations.",
        ),
        (
            "Search liquidity disclosures",
            "What do Hain Celestial's available filings say about liquidity and debt? "
            "Show the supporting passages and document IDs.",
        ),
        (
            "Explore available evidence",
            "Which local documents are available for AVITA, and which contain information "
            "about its credit agreement or financial covenants?",
        ),
        (
            "Check evidence gaps",
            "Search FMC's available filings for covenant waivers. Distinguish what the "
            "retrieved passages establish from information that is missing.",
        ),
    ),
    "Credit Analysis": (
        (
            "Full credit review",
            "Analyze borrower SYN001 for the reporting period 2025-09-30, using an "
            "information cutoff of 2025-09-30. Retrieve financials, calculate covenant "
            "compliance and headroom, run the Logistic Regression risk model, present "
            "bullish and bearish views, and recommend an exposure action. My criteria "
            "are current compliance, sufficient headroom, stable financial trends, "
            "and no unexplained material evidence gaps.",
        ),
        (
            "Forecast next-quarter risk",
            "Review SYN002 for 2025-09-30 with an information cutoff of 2025-09-30. "
            "Include a next-quarter forecast using Logistic Regression alongside current "
            "covenant compliance, bullish and bearish views, and a recommendation. "
            "Use compliance, headroom, and deteriorating financial trends as credit "
            "criteria. Distinguish predicted risk from observed results.",
        ),
        (
            "Investigate a breach",
            "Analyze SYN003 for 2025-06-30 with an information cutoff of 2025-06-30. "
            "Explain calculated covenant compliance and headroom, give bullish and "
            "bearish views, and recommend an exposure action. Keep ML off. My criteria "
            "are covenant compliance and the strength of evidence for mitigating risks.",
        ),
        (
            "Weigh bull and bear views",
            "Analyze SYN004 for 2025-09-30 with an information cutoff of 2025-09-30 "
            "and Logistic Regression enabled. Compare the bullish and bearish arguments "
            "and explain which evidence drives the final recommendation. My criteria "
            "are covenant headroom, financial trends, and forecast risk.",
        ),
        (
            "Review missing inputs",
            "Review SYN007 for 2025-09-30 with an information cutoff of 2025-09-30 "
            "and Logistic Regression enabled. Identify missing financial inputs and "
            "explain their effect on calculations, the forecast, bull and bear views, "
            "and the final recommendation. My criterion is sufficient evidence for "
            "any substantive exposure action; do not fill in missing values.",
        ),
    ),
}


def initialize_session() -> None:
    st.session_state.setdefault(f"{PREFIX}mode", MODES[0])
    if f"{PREFIX}backend" not in st.session_state:
        backend = ChatBackend(model=os.getenv("LLM_MODEL") or DEFAULT_MODEL)
        st.session_state[f"{PREFIX}backend"] = backend
        st.session_state[f"{PREFIX}session_id"] = backend.session.session_id
        st.session_state[f"{PREFIX}messages"] = {mode: [] for mode in MODES}
        st.session_state[f"{PREFIX}busy"] = False


def question_key(mode: str) -> str:
    # A new widget on reset also clears any unsent text held in the browser.
    session_id = st.session_state[f"{PREFIX}session_id"]
    return f"{PREFIX}question_{mode.lower().replace(' ', '_')}_{session_id}"


def copy_question(mode: str, question: str) -> None:
    """Prefill the composer; the user edits and submits it separately."""
    st.session_state[question_key(mode)] = question


def select_mode(mode: str) -> None:
    st.session_state[f"{PREFIX}mode"] = mode


def reset_session() -> None:
    """Clear this prototype's state while keeping the selected navigation mode."""
    backend = st.session_state.get(f"{PREFIX}backend")
    if backend is not None:
        backend.close()
    for key in list(st.session_state):
        if key.startswith(PREFIX) and key != f"{PREFIX}mode":
            del st.session_state[key]
    initialize_session()


def render_message(message: dict, pending: dict | None = None) -> None:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
            return
        turn = message["turn"]
        update = live_response(turn)
        if pending is not None and pending["interaction_id"] == turn.interaction_id:
            try:
                asyncio.run(
                    st.session_state[f"{PREFIX}backend"].run_turn(
                        pending["mode"], pending["question"], turn, on_update=update
                    )
                )
            finally:
                st.session_state[f"{PREFIX}busy"] = False
        response_details(turn)


def main() -> None:
    st.set_page_config(page_title="Agent playground", page_icon="💬", layout="wide")
    load_dotenv(ROOT / ".env", override=False)
    try:
        configure_observability()
    except Exception as error:
        st.error(f"Monitoring configuration failed ({type(error).__name__}). Check .env settings.")
        st.stop()
    initialize_session()
    busy = st.session_state[f"{PREFIX}busy"]
    pending = st.session_state.pop(f"{PREFIX}pending", None)
    st.html(Path(__file__).with_name("index.html").read_text(encoding="utf-8"))

    session_column, reset_column = st.columns([5, 1])
    with session_column:
        st.caption(f"Session: {st.session_state[f'{PREFIX}session_id']}")
    with reset_column:
        st.button("Reset session", on_click=reset_session, disabled=busy, use_container_width=True)

    mode = st.session_state[f"{PREFIX}mode"]
    st.subheader("Choose a mode")
    for index, (column, option) in enumerate(zip(st.columns(2), MODES, strict=True)):
        with column:
            with st.container(border=True, key=f"mode_card_{index}"):
                st.button(
                    option,
                    key=f"{PREFIX}choose_{index}",
                    type="primary" if mode == option else "secondary",
                    icon=(
                        ":material/check_circle:" if mode == option else ":material/arrow_forward:"
                    ),
                    on_click=select_mode,
                    args=(option,),
                    disabled=busy,
                    use_container_width=True,
                )
                st.caption(MODE_DESCRIPTIONS[option])
    st.caption(f"Selected mode: **{mode}**")
    chat_column, examples_column = st.columns([2.2, 1], gap="large")
    with examples_column:
        with st.container(border=True, key="question_library"):
            st.subheader("Try a question")
            st.caption("Click a title to copy the full question into chat. Edit it before sending.")
            for index, (title, sample) in enumerate(SAMPLE_QUESTIONS[mode]):
                st.button(
                    title,
                    key=f"{PREFIX}sample_{mode}_{index}",
                    help=sample,
                    on_click=copy_question,
                    args=(mode, sample),
                    disabled=busy,
                    icon=":material/arrow_outward:",
                    use_container_width=True,
                )
            st.divider()
            st.caption("SEC filings for evidence search · Synthetic borrowers for credit analysis")

    with chat_column:
        heading_column, help_column = st.columns([3, 1])
        with heading_column:
            st.subheader(mode)
        with help_column:
            with st.popover("Help", icon=":material/help_outline:"):
                st.markdown("**What to include in your prompt**")
                if mode == "Credit Analysis":
                    st.markdown(
                        "- Borrower ID, reporting period, and information cutoff.\n"
                        "- Requested analysis and ML preference (Logistic Regression, Stub, Off).\n"
                        "- Your credit criteria and any constraints."
                    )
                    st.caption("All analysis inputs come from your message; no form is required.")
                else:
                    st.markdown(
                        "- Company or ticker to search.\n"
                        "- The covenant, disclosure, or topic you want to find.\n"
                        "- Any document or reporting period to focus on."
                    )
                st.caption("Choose a sample on the right for a ready-to-edit prompt.")

        messages = st.session_state[f"{PREFIX}messages"][mode]
        with st.container(height=390, border=True, key="conversation", autoscroll=True):
            if not messages:
                st.html(
                    '<div class="chat-welcome"><span class="welcome-mark">↗</span>'
                    "<h3>Start with a question.</h3>"
                    "<p>Describe what you want to explore, or choose a sample to get started.</p>"
                    "</div>"
                )
            for message in messages:
                render_message(message, pending)
        placeholder = (
            "Ask about a company or filing…"
            if mode == "Evidence Search"
            else "Describe the borrower, dates, and analysis you need…"
        )
        credentials_available = bool(os.getenv("OPENAI_API_KEY", "").strip())
        question = st.chat_input(
            placeholder, key=question_key(mode), disabled=busy or not credentials_available
        )
        if not credentials_available:
            st.info("Set OPENAI_API_KEY in the repository .env to enable agent responses.")
        st.caption(
            "Monitoring configured · Content capture "
            + ("enabled" if capture_content_enabled() else "disabled")
            + " · Credit data and ML training are synthetic."
        )
        if pending is not None:
            # Render the trigger widget on the processing run so its submitted value
            # is consumed before restoring enabled controls on the next rerun.
            st.rerun()
        if question and question.strip():
            turn = ChatTurn()
            messages.extend(
                [
                    {"role": "user", "content": question.strip()},
                    {"role": "assistant", "turn": turn},
                ]
            )
            st.session_state[f"{PREFIX}pending"] = {
                "mode": mode,
                "question": question.strip(),
                "interaction_id": turn.interaction_id,
            }
            st.session_state[f"{PREFIX}busy"] = True
            st.rerun()


if __name__ == "__main__":
    main()
