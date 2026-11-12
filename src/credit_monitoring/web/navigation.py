"""Session-owned navigation and edit buffers, independent of widget lifetimes."""

from dataclasses import dataclass, field
from typing import Any

import streamlit as st


@dataclass
class WorkspaceContext:
    page: str = "Portfolio"
    return_page: str = "Portfolio"
    selections: dict[str, Any] = field(default_factory=dict)


SELECTIONS = {
    "portfolio_borrower",
    "portfolio_period",
    "portfolio_cutoff",
    "portfolio_search",
    "portfolio_status_filter",
    "portfolio_sector_filter",
    "portfolio_include_reviews",
    "portfolio_batch_question",
    "portfolio_batch_criteria",
    "portfolio_batch_context",
    "analysis_borrower",
    "analysis_period",
    "analysis_cutoff",
    "analysis_prediction",
    "analysis_version",
    "analysis_section",
    "analysis_show_chat",
    "risk_borrower",
    "risk_period",
    "risk_cutoff",
    "risk_queue_filter",
    "board_report_selection",
    "board_period",
    "board_cutoff",
    "documents_borrower",
    "documents_view",
}
EDIT_PREFIXES = (
    "analysis_report_",
    "analysis_triage_",
    "analysis_validation_",
    "analysis_check_",
    "analysis_flag_",
)


def context() -> WorkspaceContext:
    return st.session_state.setdefault("workspace_context", WorkspaceContext())


def restore_workspace() -> None:
    for key, value in context().selections.items():
        # Reassign live values too: detach them from widgets before Streamlit
        # removes controls belonging to the page we are leaving.
        st.session_state[key] = st.session_state.get(key, value)


def remember_workspace() -> None:
    saved = context()
    saved.page = st.session_state.get("preview_page", "Portfolio")
    for key in st.session_state:
        if key in SELECTIONS or key.startswith(EDIT_PREFIXES):
            saved.selections[key] = st.session_state[key]


def navigate(page: str) -> None:
    if page in {"User guide", "Settings", "Documents & data"}:
        current = st.session_state.get("preview_page", "Portfolio")
        if current not in {"User guide", "Settings", "Documents & data"}:
            context().return_page = current
    st.session_state._preview_next_page = page
    st.rerun()
