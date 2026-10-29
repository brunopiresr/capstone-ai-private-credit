"""Local-only styling for the Streamlit interaction preview."""

import streamlit as st


def render_preview_style() -> None:
    st.markdown(
        """
        <style>
        .stApp {
          --ink:#1d3028; --muted:#738077; --line:#e2e8e1;
          background:#f8faf7; color:var(--ink);
          font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        .stMain .block-container { max-width:1500px; padding:3rem 2.7rem 4rem; }
        [data-testid="stSidebar"] { background:#f0f4ee; border-right:1px solid #dfe6dd; }
        [data-testid="stSidebar"] .block-container { padding-top:1.5rem; }
        [data-testid="stSidebar"] [data-testid="stRadio"] label p { font-size:.92rem; }
        [data-testid="stSidebar"] [data-testid="stRadio"] > div { gap:.6rem; }
        h1,h2,h3,h4 { color:var(--ink); font-family:inherit; letter-spacing:-.035em; }
        h1 { font-size:2.15rem!important; font-weight:720!important; padding-bottom:.5rem; }
        h2 { font-size:1.35rem!important; font-weight:650!important; }
        h3 { font-size:1.05rem!important; font-weight:650!important; }
        p { line-height:1.6; }
        .preview-brand { display:flex; align-items:center; gap:11px; margin:0 0 24px; }
        .preview-mark { background:#214d3a; color:#d4edb0; width:40px; height:40px;
          display:grid; place-items:center; border-radius:11px; font-size:23px; }
        .preview-brand b { font-size:1.05rem; letter-spacing:-.035em; }
        .preview-brand small { display:block; color:#728075; font-size:.7rem; margin-top:2px; }
        .preview-eyebrow { font-size:.67rem; letter-spacing:.15em; text-transform:uppercase;
          color:#7a887d; font-weight:700; margin:0 0 8px; }
        .preview-subtitle { color:#718075; font-size:.93rem; margin:-.3rem 0 1.3rem; }
        .preview-ribbon { display:flex; justify-content:space-between; align-items:center;
          gap:12px; padding:10px 15px; background:#edf3e9; border:1px solid #dce6d5;
          border-radius:8px; margin-bottom:23px; color:#52674e; font-size:.76rem; }
        .preview-ribbon b { color:#315133; }
        .preview-chip { display:inline-block; font-size:.7rem; font-weight:650;
          border-radius:5px; padding:5px 9px; line-height:1.3; margin-right:5px; }
        .chip-green { color:#256044; background:#e5f0e5; }
        .chip-red { color:#aa493c; background:#fae9e4; }
        .chip-amber { color:#8d6427; background:#fbf0d9; }
        .chip-grey { color:#69746c; background:#edf0eb; }
        .preview-notice { padding:15px 18px; border-radius:9px; background:#fff6e5;
          border:1px solid #efe2c5; color:#6d5733; margin:16px 0 22px; font-size:.86rem; }
        .preview-note { padding:14px 16px; background:#f0f5ec; border-left:3px solid #aac38f;
          border-radius:0 7px 7px 0; color:#506447; margin:12px 0; font-size:.85rem; }
        .preview-micro { color:#7c887e; font-size:.72rem; line-height:1.6; }
        .preview-divider { border-top:1px solid #e3e9df; margin:22px 0; }
        .preview-source { font-size:.74rem; color:#728176; padding-top:8px; }
        .preview-case { margin-bottom:8px; color:#58734d; font-size:.68rem;
          letter-spacing:.12em; text-transform:uppercase; font-weight:700; }
        .preview-kpi-label { font-size:.74rem; color:#748174; margin-bottom:5px; }
        .preview-kpi-value { font-size:1.85rem; font-weight:650; letter-spacing:-.05em; }
        .preview-kpi-help { font-size:.72rem; color:#80907d; margin-top:6px; }
        [data-testid="stMetric"] { background:white; border:1px solid #e2e8df;
          border-radius:10px; padding:17px 19px; }
        [data-testid="stMetricValue"] { font-size:1.8rem; font-weight:650; letter-spacing:-.04em; }
        [data-testid="stMetricLabel"] { font-size:.76rem; color:#728173; }
        [data-testid="stMetricDelta"] { font-size:.72rem; }
        [data-testid="stVerticalBlockBorderWrapper"] > div { border-color:#e2e8df!important; }
        [data-testid="stDataFrame"] { border:1px solid #e2e8df; border-radius:9px; }
        [data-testid="stTabs"] [role="tablist"] { gap:20px; border-bottom:1px solid #e2e8df; }
        [data-testid="stTabs"] [role="tab"] { font-size:.82rem; padding:0 2px 12px; }
        .stButton > button, .stFormSubmitButton > button { border-radius:7px; font-size:.81rem; }
        .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
          background:#214d3a; border-color:#214d3a; color:white;
        }
        [data-testid="stCaptionContainer"] { color:#7c877e; }
        [data-testid="stChatMessage"] { border-radius:8px; background:#f1f5ed; }
        [data-testid="stChatMessage"] p { font-size:.84rem; }
        [data-testid="stExpander"] { background:white; border-color:#e2e8df; }
        [data-testid="stForm"] { border-color:#e2e8df; border-radius:9px; background:white; }
        @media(max-width:900px) {
          .stMain .block-container { padding:2rem 1rem 3rem; }
          .preview-ribbon { align-items:flex-start; flex-direction:column; gap:4px; }
          h1 { font-size:1.75rem!important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
