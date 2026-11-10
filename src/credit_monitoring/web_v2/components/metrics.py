"""Reusable UI KPI metric cards and badges for web_v2."""

from typing import Literal

import streamlit as st


def render_badge(
    label: str,
    status: Literal["compliant", "breach", "watch", "unassessed", "neutral"] = "neutral",
) -> str:
    """Return HTML string for a colored status pill badge."""
    color_map = {
        "compliant": "cm-badge-green",
        "breach": "cm-badge-red",
        "watch": "cm-badge-amber",
        "unassessed": "cm-badge-gray",
        "neutral": "cm-badge-gray",
    }
    css_class = color_map.get(status, "cm-badge-gray")
    return f'<span class="cm-badge {css_class}">{label}</span>'


def render_kpi_card(label: str, value: str | int | float, subtext: str | None = None) -> None:
    """Render a styled KPI metric card in the current column."""
    sub_html = f'<div class="cm-kpi-delta">{subtext}</div>' if subtext else ""
    st.markdown(
        f"""
        <div class="cm-kpi-card">
            <div class="cm-kpi-label">{label}</div>
            <div class="cm-kpi-val">{value}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
