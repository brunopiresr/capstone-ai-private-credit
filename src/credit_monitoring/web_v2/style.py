"""Modern, accessible styling for the role-based credit monitoring interface."""

import streamlit as st


def render_v2_style() -> None:
    st.markdown(
        """
        <style>
        /* Base typography & color palette */
        :root {
            --cm-navy: #0f172a;
            --cm-emerald: #047857;
            --cm-emerald-bg: #ecfdf5;
            --cm-emerald-border: #a7f3d0;
            --cm-coral: #b91c1c;
            --cm-coral-bg: #fef2f2;
            --cm-coral-border: #fecaca;
            --cm-amber: #b45309;
            --cm-amber-bg: #fffbeb;
            --cm-amber-border: #fde68a;
            --cm-slate-50: #f8fafc;
            --cm-slate-100: #f1f5f9;
            --cm-slate-200: #e2e8f0;
            --cm-slate-400: #94a3b8;
            --cm-slate-600: #475569;
            --cm-slate-700: #334155;
            --cm-slate-900: #0f172a;
        }

        .stApp {
            background-color: #f8fafc;
            color: var(--cm-slate-900);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                Roboto, Helvetica, Arial, sans-serif;
        }

        .stMain .block-container {
            max-width: 1440px;
            padding: 1.8rem 2rem 3.5rem;
        }

        /* Top Header & Branding */
        .cm-top-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 20px;
            background: white;
            border: 1px solid var(--cm-slate-200);
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
        }

        .cm-brand-group {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .cm-brand-logo {
            width: 38px;
            height: 38px;
            background: linear-gradient(135deg, #0f172a, #1e293b);
            color: #34d399;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            border-radius: 10px;
            font-weight: 700;
        }

        .cm-brand-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--cm-slate-900);
            line-height: 1.2;
            letter-spacing: -0.02em;
        }

        .cm-brand-subtitle {
            font-size: 0.76rem;
            font-weight: 500;
            color: var(--cm-slate-600);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        /* Pill status tags */
        .cm-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 9999px;
            line-height: 1.2;
        }

        .cm-badge-green {
            background-color: var(--cm-emerald-bg);
            color: var(--cm-emerald);
            border: 1px solid var(--cm-emerald-border);
        }

        .cm-badge-amber {
            background-color: var(--cm-amber-bg);
            color: var(--cm-amber);
            border: 1px solid var(--cm-amber-border);
        }

        .cm-badge-red {
            background-color: var(--cm-coral-bg);
            color: var(--cm-coral);
            border: 1px solid var(--cm-coral-border);
        }

        .cm-badge-gray {
            background-color: var(--cm-slate-100);
            color: var(--cm-slate-600);
            border: 1px solid var(--cm-slate-200);
        }

        /* Metric KPI Card */
        .cm-kpi-card {
            background: white;
            border: 1px solid var(--cm-slate-200);
            border-radius: 10px;
            padding: 14px 18px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
        }

        .cm-kpi-label {
            font-size: 0.78rem;
            font-weight: 600;
            color: var(--cm-slate-600);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 4px;
        }

        .cm-kpi-val {
            font-size: 1.85rem;
            font-weight: 750;
            letter-spacing: -0.03em;
            color: var(--cm-slate-900);
        }

        .cm-kpi-delta {
            font-size: 0.75rem;
            color: var(--cm-slate-600);
            margin-top: 4px;
        }

        /* Banner info box */
        .cm-banner {
            padding: 12px 16px;
            background: white;
            border-left: 4px solid #0f172a;
            border-radius: 4px 8px 8px 4px;
            margin-bottom: 18px;
            border-top: 1px solid var(--cm-slate-200);
            border-right: 1px solid var(--cm-slate-200);
            border-bottom: 1px solid var(--cm-slate-200);
        }

        /* Suggestion chips for Chat Assistant */
        .cm-prompt-chip {
            display: inline-block;
            background: #f1f5f9;
            color: #1e293b;
            border: 1px solid #cbd5e1;
            border-radius: 20px;
            padding: 5px 12px;
            font-size: 0.78rem;
            margin: 3px 4px 3px 0;
            cursor: pointer;
            transition: all 0.15s ease-in-out;
            text-decoration: none;
        }

        .cm-prompt-chip:hover {
            background: #e2e8f0;
            border-color: #94a3b8;
        }

        /* Clean tabs styling */
        [data-testid="stTabs"] [role="tablist"] {
            gap: 24px;
            border-bottom: 2px solid var(--cm-slate-200);
            padding-bottom: 2px;
            margin-bottom: 18px;
        }

        [data-testid="stTabs"] [role="tab"] {
            font-size: 0.92rem;
            font-weight: 600;
            padding: 6px 4px 10px;
            color: var(--cm-slate-600);
        }

        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            color: #0f172a !important;
            border-bottom: 2px solid #0f172a;
        }

        /* Button polish */
        .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
            background-color: #0f172a !important;
            border-color: #0f172a !important;
            color: white !important;
            font-weight: 600;
            border-radius: 8px;
        }

        .stButton > button[kind="secondary"], .stFormSubmitButton > button[kind="secondary"] {
            border-radius: 8px;
            font-weight: 500;
        }

        /* Chat messages */
        [data-testid="stChatMessage"] {
            background-color: white;
            border: 1px solid var(--cm-slate-200);
            border-radius: 10px;
            margin-bottom: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
