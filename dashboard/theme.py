"""
Cuemath design system for the Streamlit dashboard.

Palette:
  --cue-navy:    #0E1B3D  deep navy — sidebar bg, display headings
  --cue-green:   #2DBD6E  brand green — primary CTA, Good RAG
  --cue-orange:  #FF6534  warm orange — accent, highlights
  --cue-ground:  #F4F6FF  blue-white page ground
  --cue-surface: #FFFFFF  card surface
  --cue-muted:   #5B6B82  secondary text
  --cue-border:  #E4EAF3  subtle borders
  --cue-amber:   #F59E0B  Average RAG
  --cue-red:     #E84C3D  Bad RAG
"""
from __future__ import annotations
import streamlit as st

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap');

:root {
  --cue-navy:    #0E1B3D;
  --cue-green:   #2DBD6E;
  --cue-orange:  #FF6534;
  --cue-ground:  #F4F6FF;
  --cue-surface: #FFFFFF;
  --cue-muted:   #5B6B82;
  --cue-border:  #E4EAF3;
  --cue-amber:   #F59E0B;
  --cue-red:     #E84C3D;
  --cue-pending: #94A3B8;
}

/* ── Page ground ─────────────────────────────────────────────────────────── */
.stApp {
  background: var(--cue-ground) !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
[data-testid="stAppViewContainer"] {
  background: var(--cue-ground) !important;
}
[data-testid="block-container"] {
  padding-top: 1.75rem !important;
  max-width: 1400px !important;
}

/* ── Typography ──────────────────────────────────────────────────────────── */
h1, h2, h3, h4, .stTitle {
  font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
  color: var(--cue-navy) !important;
}
h1 {
  font-size: 1.7rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.025em !important;
}
h2 {
  font-size: 1.3rem !important;
  font-weight: 700 !important;
}
h3 {
  font-size: 1.05rem !important;
  font-weight: 700 !important;
}

/* ── Sidebar — deep navy command rail ──────────────────────────────────────── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"],
[data-testid="stSidebarContent"] {
  background: var(--cue-navy) !important;
}
[data-testid="stSidebarContent"] {
  padding-top: 0 !important;
}
[data-testid="stSidebar"] * {
  color: #FFFFFF !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small,
[data-testid="stSidebar"] caption {
  color: rgba(255,255,255,0.45) !important;
}
[data-testid="stSidebar"] hr {
  border-color: rgba(255,255,255,0.1) !important;
  margin: 0.75rem 0 !important;
}
/* Sidebar markdown h3 → section label */
[data-testid="stSidebar"] h3 {
  font-size: 0.62rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  color: rgba(255,255,255,0.4) !important;
  margin: 1rem 0 0.35rem !important;
}
[data-testid="stSidebar"] .stMarkdown h3 {
  font-size: 0.62rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  color: rgba(255,255,255,0.4) !important;
  margin: 1rem 0 0.35rem !important;
}

/* Sidebar primary button → green */
[data-testid="stSidebar"] .stButton > button {
  background: var(--cue-green) !important;
  color: #FFFFFF !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  transition: background 0.15s ease, box-shadow 0.15s ease !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: #25A85F !important;
  box-shadow: 0 4px 14px rgba(45,189,110,0.35) !important;
}
/* Second sidebar button → ghost */
[data-testid="stSidebar"] .stButton:nth-of-type(2) > button,
[data-testid="stSidebar"] button[kind="secondary"] {
  background: rgba(255,255,255,0.08) !important;
  border: 1px solid rgba(255,255,255,0.18) !important;
  color: rgba(255,255,255,0.85) !important;
}
[data-testid="stSidebar"] .stButton:nth-of-type(2) > button:hover,
[data-testid="stSidebar"] button[kind="secondary"]:hover {
  background: rgba(255,255,255,0.14) !important;
}

/* Sidebar selectbox, date input */
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div,
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"] > div {
  background: rgba(255,255,255,0.07) !important;
  border-color: rgba(255,255,255,0.15) !important;
  color: #FFFFFF !important;
  border-radius: 8px !important;
}
[data-testid="stSidebar"] label {
  font-size: 0.8rem !important;
  color: rgba(255,255,255,0.7) !important;
}
[data-testid="stSidebar"] input {
  color: #FFFFFF !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] svg,
[data-testid="stSidebar"] [data-baseweb="input"] svg {
  fill: rgba(255,255,255,0.5) !important;
}
/* Sidebar checkbox */
[data-testid="stSidebar"] [data-testid="stCheckbox"] label {
  font-size: 0.85rem !important;
  color: rgba(255,255,255,0.8) !important;
}
/* Download button in sidebar */
[data-testid="stSidebar"] .stDownloadButton > button {
  background: rgba(45,189,110,0.15) !important;
  border: 1px solid rgba(45,189,110,0.4) !important;
  color: #FFFFFF !important;
  border-radius: 8px !important;
}

/* ── Main buttons ──────────────────────────────────────────────────────────── */
.stButton > button {
  border-radius: 8px !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  transition: all 0.15s ease !important;
  border: none !important;
}
/* Primary button */
.stButton > button[kind="primary"],
.stButton > button:not([kind="secondary"]) {
  background: var(--cue-green) !important;
  color: #FFFFFF !important;
}
.stButton > button[kind="primary"]:hover {
  background: #25A85F !important;
  box-shadow: 0 4px 14px rgba(45,189,110,0.35) !important;
}

/* ── Metrics ───────────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
  background: var(--cue-surface) !important;
  border-radius: 12px !important;
  padding: 1rem 1.25rem !important;
  border: 1px solid var(--cue-border) !important;
  box-shadow: 0 1px 4px rgba(14,27,61,0.05) !important;
}
[data-testid="stMetricLabel"] {
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.07em !important;
  color: var(--cue-muted) !important;
}
[data-testid="stMetricLabel"] > div,
[data-testid="stMetricLabel"] p {
  color: var(--cue-muted) !important;
}
[data-testid="stMetricValue"] {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 1.6rem !important;
  font-weight: 800 !important;
  color: var(--cue-navy) !important;
}
[data-testid="stMetricValue"] > div {
  color: var(--cue-navy) !important;
}

/* ── Selectbox (main area) ─────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div,
[data-baseweb="select"] > div {
  border-radius: 8px !important;
  border-color: var(--cue-border) !important;
  background: var(--cue-surface) !important;
}

/* ── DataFrame ─────────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
  border-radius: 12px !important;
  overflow: hidden !important;
  border: 1px solid var(--cue-border) !important;
  box-shadow: 0 1px 4px rgba(14,27,61,0.05) !important;
}

/* ── Expander ──────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
  border-radius: 10px !important;
  border-color: var(--cue-border) !important;
  background: var(--cue-surface) !important;
  box-shadow: 0 1px 3px rgba(14,27,61,0.04) !important;
}
[data-testid="stExpander"] summary {
  border-radius: 10px !important;
  padding: 0.75rem 1rem !important;
}

/* ── Info / warning / success ──────────────────────────────────────────────── */
[data-testid="stAlert"] {
  border-radius: 10px !important;
}

/* ── Caption ───────────────────────────────────────────────────────────────── */
.stCaption, .stCaption p {
  color: var(--cue-muted) !important;
  font-size: 0.8rem !important;
}

/* ── Progress bar ──────────────────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div > div {
  background: var(--cue-green) !important;
}

/* ── Spinner ───────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] * {
  border-top-color: var(--cue-green) !important;
}

/* ── Divider ───────────────────────────────────────────────────────────────── */
hr {
  border-color: var(--cue-border) !important;
  margin: 1rem 0 !important;
}

/* ── Back button ───────────────────────────────────────────────────────────── */
button[data-testid="stBaseButton-secondary"] {
  background: var(--cue-surface) !important;
  color: var(--cue-navy) !important;
  border: 1px solid var(--cue-border) !important;
}
button[data-testid="stBaseButton-secondary"]:hover {
  border-color: var(--cue-green) !important;
  color: var(--cue-green) !important;
}

/* ── Download button ───────────────────────────────────────────────────────── */
.stDownloadButton > button {
  background: var(--cue-navy) !important;
  color: #FFFFFF !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
}
.stDownloadButton > button:hover {
  background: #162952 !important;
}

/* ── Green 3px rule at the very top ──────────────────────────────────────── */
.stApp > header {
  background: transparent !important;
  border-bottom: none !important;
}
[data-testid="stHeader"] {
  background: transparent !important;
}
/* The rule itself */
.cue-top-rule {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--cue-green);
  z-index: 999999;
  pointer-events: none;
}
</style>
"""

_FONT_LINK = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
"""


def inject_theme() -> None:
    """Inject Cuemath design system CSS + fonts + the 3px green top rule."""
    st.markdown(_FONT_LINK, unsafe_allow_html=True)
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)
    # The 3px brand rule
    st.markdown('<div class="cue-top-rule"></div>', unsafe_allow_html=True)


def sidebar_brand() -> None:
    """Render Cuemath wordmark + product label inside the sidebar."""
    st.markdown(
        """
        <div style="
          padding: 1.5rem 1rem 1.25rem;
          border-bottom: 1px solid rgba(255,255,255,0.1);
          margin-bottom: 0.5rem;
        ">
          <div style="
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 1.4rem; font-weight: 800;
            color: #FFFFFF; letter-spacing: -0.02em;
            line-height: 1;
          ">
            <span style="color:#2DBD6E">cue</span>math
          </div>
          <div style="
            font-size: 0.6rem; font-weight: 700;
            color: rgba(255,255,255,0.35);
            text-transform: uppercase; letter-spacing: 0.12em;
            margin-top: 5px;
          ">Curriculum Ops · v3.1</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
