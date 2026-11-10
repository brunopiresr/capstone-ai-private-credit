"""Top navigation header, role switcher, and reporting controls for web_v2."""

import os
from datetime import date

import streamlit as st


def render_header(periods: list[date]) -> tuple[str, date | None, date]:
    """Render top application brand, role switcher, and date controls.

    Returns:
        (active_role, selected_period, information_cutoff)
    """
    # 1. Branding banner
    api_key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())
    status_pill = (
        '<span class="cm-badge cm-badge-green">● AI Copilot Online</span>'
        if api_key_present
        else '<span class="cm-badge cm-badge-amber">○ AI Offline (No API Key)</span>'
    )

    st.markdown(
        f"""
        <div class="cm-top-header">
            <div class="cm-brand-group">
                <div class="cm-brand-logo">◈</div>
                <div>
                    <div class="cm-brand-title">Credit Monitor</div>
                    <div class="cm-brand-subtitle">Private Credit Intelligence Platform</div>
                </div>
            </div>
            <div>{status_pill}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2. Controls bar: Role selection & Date scopes
    col_role, col_period, col_cutoff = st.columns([1.8, 1, 1])

    with col_role:
        role_options = ["👤 Credit Analyst", "🛡️ Risk Manager", "📁 Documents & Data"]
        # Default view: credit analyst as explicitly requested
        if "v2_active_role" not in st.session_state:
            st.session_state.v2_active_role = "👤 Credit Analyst"

        active_role = (
            st.segmented_control(
                "Select Workspace Role",
                role_options,
                key="v2_active_role",
                label_visibility="collapsed",
            )
            or "👤 Credit Analyst"
        )

    with col_period:
        period_strings = (
            ["latest", *[p.isoformat() for p in reversed(periods)]] if periods else ["latest"]
        )
        def period_label_func(val: str) -> str:
            return "Latest Eligible Period" if val == "latest" else f"Period End: {val}"

        selected_period_str = st.selectbox(
            "Reporting Period",
            period_strings,
            format_func=period_label_func,
            key="v2_period_select",
            label_visibility="collapsed",
        )
        selected_period = (
            None if selected_period_str == "latest" else date.fromisoformat(selected_period_str)
        )

    with col_cutoff:
        default_cutoff = periods[-1] if periods else date.today()
        cutoff_date = st.date_input(
            "Information Cutoff",
            default_cutoff,
            key="v2_cutoff_select",
            label_visibility="collapsed",
        )

    st.divider()

    return active_role, selected_period, cutoff_date
