"""Documents and data management view for web_v2."""

import streamlit as st

from credit_monitoring.web.documents import render_documents_page


def render_documents_view() -> None:
    """Render documents and data workspace with clean styling."""
    st.markdown("### Document & Evidence Workspace")
    st.caption("Manage SEC filings, registered sources, extraction, and index maintenance.")
    render_documents_page()
