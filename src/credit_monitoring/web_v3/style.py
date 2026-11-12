"""Readable, responsive presentation scoped to the V3 app."""

import streamlit as st


def render_style() -> None:
    st.html("""<style>
    .stApp {background:#f6f8fa; color:#182c38;}
    .stMain .block-container {max-width:1360px; padding:5rem 2.2rem 4rem;}
    h1,h2,h3 {letter-spacing:-.025em; color:#163d47;}
    h1 {font-size:2.25rem;} h2 {font-size:1.45rem;} h3 {font-size:1.15rem;}
    p, li {line-height:1.65;}
    [data-testid="stSidebar"] {background:#fff; border-right:1px solid #dbe4e9;}
    [data-testid="stMetric"] {background:#fff; border:1px solid #dbe4e9;
      border-radius:10px; padding:16px;}
    [data-testid="stChatMessage"] {background:#fff; border:1px solid #dbe4e9;
      border-radius:12px; padding:1.2rem; margin-bottom:1rem;}
    [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li {
      font-size:1rem!important; line-height:1.75!important;}
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
      background:#eaf3f6; border-color:#bdd6df;}
    [data-testid="stExpander"], [data-testid="stForm"] {background:#fff;}
    .v3-badge {display:inline-block; border-radius:6px; padding:6px 10px;
      margin:0 8px 8px 0; background:#e8eff3; color:#163d47; font-size:.9rem;}
    .v3-next {background:#eaf4ee; border-left:4px solid #28624a;
      border-radius:8px; padding:16px 20px; margin:16px 0;}
    .st-key-v3_actionbar {position:sticky; top:3.75rem; z-index:20;
      background:#f6f8fa; padding:8px 0; border-bottom:1px solid #dbe4e9;}
    button:focus-visible, input:focus-visible, textarea:focus-visible,
    [role="tab"]:focus-visible {outline:3px solid #267286!important; outline-offset:3px;}
    @media(max-width:950px) {
      .stMain .block-container {padding:4.5rem 1rem 3rem;}
      [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
      [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        min-width:min(100%,300px); flex:1 1 300px;}
    }
    @media(max-width:600px) {
      h1 {font-size:1.7rem!important;}
      [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {flex-basis:100%;}
      [data-testid="stTabs"] [role="tablist"] {overflow-x:auto;}
    }
    </style>""")
