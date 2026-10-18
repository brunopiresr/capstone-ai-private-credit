"""Shared presentation for the analyst workspace."""

# ruff: noqa: E501

import streamlit as st


def render_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
        :root {
          --ink: #172720; --muted: #66756d; --line: #e4e9e3; --paper: #f7f8f5;
          --green: #214d3a; --green-soft: #e6f0e7; --lime: #c8ef76; --amber: #f5d88d;
          --red: #c9584b; --card: #ffffff;
        }
        html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; color: var(--ink); }
        .stApp { background: var(--paper); }
        [data-testid="stHeader"] { background: rgba(247,248,245,.94); }
        [data-testid="stSidebar"] { background: #f0f3ed; border-right: 1px solid var(--line); }
        [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
        .block-container { max-width: 1440px; padding: 1.5rem 2.6rem 3rem; }
        h1, h2, h3 { font-family: 'Manrope', sans-serif; letter-spacing: -0.035em; color: var(--ink); }
        h1 { font-size: 2.3rem !important; font-weight: 800 !important; }
        h2 { font-size: 1.35rem !important; font-weight: 750 !important; }
        .brand { display:flex; align-items:center; gap:.7rem; margin:.35rem 0 1.8rem; }
        .brand-mark { width:2.35rem; height:2.35rem; display:grid; place-items:center; border-radius:.75rem; background:var(--green); color:var(--lime); font-size:1.25rem; font-weight:700; }
        .brand-name { font: 800 1rem 'Manrope',sans-serif; line-height:1.1; }
        .brand-caption { color:var(--muted); font-size:.7rem; margin-top:.15rem; }
        .eyebrow { color:var(--green); text-transform:uppercase; letter-spacing:.12em; font-size:.7rem; font-weight:700; }
        .page-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding-bottom:1.1rem; border-bottom:1px solid var(--line); margin-bottom:1.45rem; }
        .page-subtitle { color:var(--muted); margin-top:-.6rem; font-size:.97rem; }
        .demo-pill { border:1px solid #d8e5d6; background:#eef5e9; border-radius:99px; color:var(--green); padding:.45rem .75rem; font-size:.73rem; font-weight:700; white-space:nowrap; }
        .panel { background:var(--card); border:1px solid var(--line); border-radius:1rem; padding:1.15rem 1.25rem; box-shadow:0 2px 12px rgba(26,48,35,.025); }
        .panel-label { color:var(--muted); font-size:.76rem; font-weight:600; }
        .metric-value { font:800 1.7rem 'Manrope',sans-serif; letter-spacing:-.04em; margin-top:.4rem; }
        .metric-help { color:var(--muted); font-size:.76rem; margin-top:.25rem; }
        .status-chip { display:inline-flex; align-items:center; gap:.4rem; border-radius:99px; padding:.38rem .7rem; font-size:.72rem; line-height:1; font-weight:800; letter-spacing:.02em; }
        .status-COMPLIANT { background:var(--green-soft); color:var(--green); }
        .status-WATCH { background:#fff2d3; color:#8d5a00; }
        .status-BREACH { background:#fbe8e5; color:#a63e34; }
        .status-INCOMPLETE { background:#ecefed; color:#53615a; }
        .kicker { font-size:.74rem; color:var(--muted); }
        .source-tag { display:inline-block; background:#f0f3ee; border:1px solid var(--line); color:#42544a; border-radius:.4rem; padding:.22rem .46rem; font:600 .68rem ui-monospace,monospace; }
        .chat-note { border-left:3px solid var(--lime); background:#f2f7ea; padding:.8rem 1rem; border-radius:0 .6rem .6rem 0; color:#405447; font-size:.86rem; }
        div.stButton > button[kind="primary"] { background:var(--green); border:0; border-radius:.6rem; color:white; font-weight:700; padding:.65rem 1rem; }
        div.stButton > button[kind="primary"]:hover { background:#173b2b; border:0; color:white; }
        [data-testid="stMetric"] { background:var(--card); border:1px solid var(--line); border-radius:.9rem; padding:1rem 1.05rem; }
        [data-testid="stMetricLabel"] { color:var(--muted); }
        [data-testid="stMetricValue"] { font-family:'Manrope',sans-serif; font-weight:800; letter-spacing:-.04em; }
        div[data-testid="stTabs"] button { font-weight:700; }
        [data-testid="stExpander"] { border-color:var(--line); border-radius:.8rem; }
        @media (max-width: 760px) { .block-container { padding:1rem 1rem 2rem; } .page-head { flex-direction:column; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
