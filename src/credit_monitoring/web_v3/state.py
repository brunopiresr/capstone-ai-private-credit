"""V3-owned routes and edit buffers survive Streamlit widget cleanup."""

from collections.abc import Callable

import streamlit as st


def restore() -> None:
    for key, value in st.session_state.get("_v3_memory", {}).items():
        st.session_state[key] = st.session_state.get(key, value)
    for key, value in st.session_state.pop("_v3_route", {}).items():
        st.session_state[key] = value


def remember() -> None:
    st.session_state["_v3_memory"] = {
        key: st.session_state[key] for key in st.session_state if key.startswith("v3_")
    }


def go(page: str, borrower: str | None = None, section: str | None = None) -> None:
    changes = {"v3_page": page}
    if borrower:
        changes["v3_borrower"] = borrower
    if section:
        changes["v3_section"] = section
    st.session_state["_v3_route"] = changes
    st.rerun()


def attempt(callback: Callable, message: str = "Saved."):
    try:
        result = callback()
    except ValueError as error:
        st.warning(str(error))
    except Exception as error:
        st.error(
            f"Action failed ({type(error).__name__}). Saved work is retained; retry explicitly."
        )
    else:
        st.session_state.v3_notice = message
        return result, True
    return None, False


def commit(callback: Callable, message: str = "Saved.") -> None:
    _, success = attempt(callback, message)
    if success:
        st.rerun()
